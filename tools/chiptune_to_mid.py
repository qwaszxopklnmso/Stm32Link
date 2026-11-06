# Transcribe a chiptune audio (m4s) into a multi-voice MIDI + firmware song data.
# Method: harmonic salience -> iterative Viterbi line peeling (subtract each tracked
# line's square-wave harmonic template) -> rhythm quantization -> role assignment
# by median pitch -> 4-track MIDI + Song2.c + Stm32Melody2.java + preview wav.
import subprocess, wave, io, struct
import numpy as np
from scipy import signal, ndimage

SRC = 'Audio_8bit琵琶曲.m4s'
SR, HOP = 22050, 512
FFMPEG = r'E:\ffmpeg-8.1.2-essentials_build\bin\ffmpeg.exe'
BPM = 71.0
HARM = [(2, 0.84), (3, 0.70), (4, 0.60), (5, 0.50), (6, 0.42), (7, 0.36), (8, 0.30)]

raw = subprocess.run([FFMPEG, '-v', 'error', '-i', SRC, '-ac', '1', '-ar', str(SR),
                      '-f', 's16le', '-'], capture_output=True).stdout
data = np.frombuffer(raw, np.int16).astype(np.float64) / 32768.0
dur_s = len(data) / SR

# ---------- HPSS + semitone salience ----------
f, t, Z = signal.stft(data, fs=SR, nperseg=4096, noverlap=4096 - HOP)
mag = np.abs(Z)
Hm = ndimage.median_filter(mag, size=(1, 17))
Pm = ndimage.median_filter(mag, size=(17, 1))
mask = (Hm ** 2) / (Hm ** 2 + Pm ** 2 + 1e-10)
H = Hm * mask
nframes = H.shape[1]
frame_ms = HOP * 1000.0 / SR

bin_hz = SR / 8192
def semitone_mag(m):
    freq = 440.0 * 2 ** ((m - 69) / 12)
    pos = freq / bin_hz
    i0 = int(np.floor(pos)); frac = pos - i0
    return H[i0, :] * (1 - frac) + H[i0 + 1, :] * frac

midis = np.arange(40, 93)                     # E2..A6, bass included
M = np.vstack([semitone_mag(m) for m in midis])
S0 = M.copy()
for h, wgt in HARM:
    S0 += wgt * ndimage.shift(M, (12 * np.log2(h), 0), order=1, mode='constant', cval=0.0)
S0 = ndimage.uniform_filter1d(S0, 3, axis=1)

REF = float(np.percentile(S0.max(axis=0), 90))     # global loudness reference
S_norm = S0 / (REF + 1e-9)                         # normalized once — unvoiced gate works now

def viterbi_line(S):
    nmidi = len(midis); UV = -1; nstates = nmidi + 1
    emit = np.zeros((nframes, nstates))
    emit[:, :nmidi] = np.clip(S.T, 0, 1)
    ve = S.max(axis=0)
    emit[:, :nmidi] = np.where(ve[:, None] > 0.12, emit[:, :nmidi], 0.0)
    emit[:, nmidi] = 0.30
    cost = np.abs(np.arange(nstates)[None, :].T - np.arange(nstates)[None, :]) * 0.06
    cost[:, UV] = 0.7; cost[UV, :] = 0.7; cost[UV, UV] = 0.0
    cost[:nmidi, :nmidi][np.diag_indices(nmidi)] = 0.0
    dp = np.full((nframes, nstates), -1e18)
    bp = np.zeros((nframes, nstates), dtype=np.int32)
    dp[0] = emit[0]
    for i in range(1, nframes):
        tot = dp[i - 1][:, None] - cost
        bp[i] = np.argmax(tot, axis=0)
        dp[i] = tot[bp[i], np.arange(nstates)] + emit[i]
    path = np.zeros(nframes, dtype=np.int32); path[-1] = np.argmax(dp[-1])
    for i in range(nframes - 1, 0, -1):
        path[i - 1] = bp[i, path[i]]
    return np.where(path < nmidi, midis[np.clip(path, 0, nmidi - 1)], -1)

# ---------- peel 4 lines ----------
S_work = S_norm.copy()
tracks = []
midx = {m: i for i, m in enumerate(midis)}
for v in range(4):
    tr = viterbi_line(S_work)
    tracks.append(tr)
    voiced = tr >= 0
    for i in np.nonzero(voiced)[0]:
        p = int(tr[i])
        pi = midx.get(p)
        if pi is None: continue
        base = S_work[pi, i]
        S_work[pi, i] = 0.0
        for h, wgt in HARM:
            j = midx.get(int(round(p + 12 * np.log2(h))))
            if j is not None:
                S_work[j, i] = max(0.0, S_work[j, i] - wgt * base)
    print('line %d: voiced %.0f%%' % (v + 1, voiced.mean() * 100))

# ---------- tracks -> note lists with rhythm quantization ----------
grid = 60.0 / BPM / 4 * 1000          # sixteenth note in ms

def track_to_notes(tr):
    raw = []
    i = 0
    while i < nframes:
        if tr[i] >= 0:
            j = i
            while j < nframes and tr[j] == tr[i]: j += 1
            if j - i >= 2: raw.append((i * frame_ms, (j - i) * frame_ms, int(tr[i])))
            i = j
        else: i += 1
    out = []   # [pitch, start_ms, dur_ms] as lists (mutable)
    for s, d, p in raw:
        ts = round(s / grid) * grid
        dq = max(round(d / grid) * grid, grid * 0.5)
        if out and out[-1][0] == p and ts - (out[-1][1] + out[-1][2]) < 60 and out[-1][2] < grid * 4:
            out[-1][2] = ts + dq - out[-1][1]
        else:
            out.append([p, ts, dq])
    for a, b in zip(out, out[1:]):
        if a[1] + a[2] > b[1]: a[2] = b[1] - a[1]
    return [(p, t, d) for (p, t, d) in out if d >= grid * 0.5]

lines = [track_to_notes(tr) for tr in tracks]

# ---------- assign roles by median pitch, fold to bands ----------
meds = [float(np.median([p for p, t, d in ln])) if ln else 0 for ln in lines]
order = sorted(range(4), key=lambda k: -meds[k])           # high -> low
role = {order[0]: 0, order[1]: 1, order[2]: 2, order[3]: 3}
BANDS = {0: (62, 86), 1: (57, 81), 2: (52, 76), 3: (38, 58)}
def fold(p, lo, hi):
    while p > hi: p -= 12
    while p < lo: p += 12
    return p

voices = [[], [], [], []]
for li, ln in enumerate(lines):
    vi = role[li]
    lo, hi = BANDS[vi]
    for (p, t, d) in ln:
        voices[vi].append((t, d, fold(p, lo, hi)))
for vi in range(4):
    voices[vi].sort()
    # monophonize
    out = []
    for (t, d, p) in voices[vi]:
        if out and t < out[-1][0] + out[-1][1]:
            out[-1] = (out[-1][0], t - out[-1][0], out[-1][2])
            if out[-1][1] < 40: out.pop()
        out.append((t, d, p))
    voices[vi] = out
    print('V%d role: %d notes, median pitch %.0f' % (vi + 1, len(out), meds[order[vi]]))

# ---------------- write MIDI (format 1: tempo track + 4 voices) ----------------
TPQ = 480
us_q = int(60e6 / BPM)
def varlen(n):
    b = [n & 0x7F]
    n >>= 7
    while n:
        b.append((n & 0x7F) | 0x80)
        n >>= 7
    return bytes(reversed(b))

def track_chunk(events):   # events: [(tick, bytes)] sorted, absolute ticks
    data = b''
    last = 0
    for tick, ev in events:
        data += varlen(tick - last) + ev
        last = tick
    data += b'\x00\xff\x2f\x00'
    return b'MTrk' + struct.pack('>I', len(data)) + data

def ms2tick(ms):
    return int(round(ms / 1000.0 * 1e6 / us_q * TPQ))

tracks = []
# tempo track
tracks.append(track_chunk([(0, b'\xff\x51\x03' + struct.pack('>I', us_q)[1:]),
                           (0, b'\xff\x03\x0bTrack Tempo')]))
for vi in range(4):
    evs = []
    for (t, d, p) in voices[vi]:
        evs.append((ms2tick(t), bytes([0x90, p, 100])))
        evs.append((ms2tick(t + d), bytes([0x80, p, 0])))
    evs.sort(key=lambda x: x[0])
    tracks.append(track_chunk(evs))
midi = (b'MThd' + struct.pack('>IHHH', 6, 1, 5, TPQ)) + b''.join(tracks)
io.open('tools/pipa_8bit.mid', 'wb').write(midi)
print('wrote tools/pipa_8bit.mid (%d bytes)' % len(midi))

# ---------------- sequential encode + preview ----------------
def encode(lst):
    seq = []
    cur = 0
    for (t, d, p) in sorted(lst):
        gap = int(round((t - cur) / 25) * 25)
        if gap >= 100: seq.append((0, gap))
        seq.append((round(440.0 * 2 ** ((p - 69) / 12)), max(75, int(round(d / 25) * 25))))
        cur = t + d
    while seq and seq[-1][0] == 0: seq.pop()
    return seq

seqs = [encode(v) for v in voices]
for vi, s in enumerate(seqs):
    print('V%d: %d entries, %.1fs' % (vi + 1, len(s), sum(x[1] for x in s) / 1000))

def synth(active, path):
    total = max(sum(x[1] for x in seqs[vi]) for vi in active)
    buf = np.zeros(int(total / 1000 * SR) + SR // 4)
    G = [0.20, 0.15, 0.13, 0.20]
    for vi in active:
        pos = 0
        for freq, ms in seqs[vi]:
            n = int(ms / 1000 * SR)
            if freq:
                tt = np.arange(n) / SR
                env = np.minimum(tt / 0.004, 1) * np.exp(-1.2 * tt / max(ms / 1000, 0.05))
                sig = np.sin(2 * np.pi * freq * tt) if vi == 3 else \
                    np.sign(np.sin(2 * np.pi * freq * tt)) + 0.3 * np.sin(4 * np.pi * freq * tt)
                buf[pos:pos + n] += G[vi] * sig * env
            pos += n
    pk = np.abs(buf).max()
    if pk > 0: buf = buf / pk * 0.85
    with wave.open(path, 'wb') as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR)
        w.writeframes((buf * 32767).astype(np.int16).tobytes())

synth([0, 1, 2, 3], 'tools/preview_pipa8.wav')
print('preview written')

# ---------------- Song2.c / Song2.h ----------------
names = ['S2_V1', 'S2_V2', 'S2_V3', 'S2_V4']
defs = []
for vi, s in enumerate(seqs):
    rows = ',\n'.join('    {%d, %d}' % (f, m) for f, m in s)
    defs.append('const uint16_t %s[][2] = {\n%s\n};\nconst uint16_t %s_Len = sizeof(%s) / sizeof(%s[0]);'
                % (names[vi], rows, names[vi], names[vi], names[vi]))
io.open('Stm32Link_Keil/Hardware/Song2.c', 'w', encoding='ascii').write(
    '''#include "Song2.h"

// Auto-generated by tools/chiptune_to_mid.py from Audio_8bit pipa song - do not edit.
// Each entry: {frequency in Hz (0 = rest), duration in ms}.
%s

''' % '\n\n'.join(defs))
io.open('Stm32Link_Keil/Hardware/Song2.h', 'w', encoding='ascii').write('''#ifndef __SONG2_H
#define __SONG2_H

#include "stm32f10x.h"

// Auto-generated by tools/chiptune_to_mid.py (8-bit pipa song) - do not edit.
extern const uint16_t S2_V1[][2];
extern const uint16_t S2_V1_Len;
extern const uint16_t S2_V2[][2];
extern const uint16_t S2_V2_Len;
extern const uint16_t S2_V3[][2];
extern const uint16_t S2_V3_Len;
extern const uint16_t S2_V4[][2];
extern const uint16_t S2_V4_Len;

#define SONG2_STOPPED 0xFFFF

#endif
''')

# ---------------- Stm32Melody2.java ----------------
def jnum(x):
    return ('%d.0f' % x) if x else '0.0f'
blocks = []
for vi, s in enumerate(seqs):
    rows = ',\n'.join('            {%s, %d}' % (jnum(f), m) for f, m in s)
    blocks.append('        {\n%s\n        }' % rows)
io.open('with_stm32/src/main/java/qw/with_stm32/Stm32Melody2.java', 'w', encoding='ascii').write(
    '''package qw.with_stm32;

// Auto-generated by tools/chiptune_to_mid.py (8-bit pipa song) - do not edit.
// VOICES[0..3] = {melody, harmony, filler, bass}; each note {frequency Hz (0=rest), duration ms}.
public final class Stm32Melody2 {
    public static final int NUM_VOICES = 4;
    public static final float[][][] VOICES = {
%s
    };

    private Stm32Melody() {}
}
''' % ',\n'.join(blocks))
print('Song2.c/h + Stm32Melody2.java written')
