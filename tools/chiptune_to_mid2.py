# Transcribe chiptune audio v2 — fixes "melody has holes" from v1's strength-based peeling.
# v1 peeled lines by loudness: when accompaniment outguns the lead for a section, the
# tracker follows the wrong line and the lead gets subtracted away -> holes.
# v2: frame-wise peak picking (all pitches), then greedy CONTINUITY-based line tracking
# (pitch proximity + time adjacency). Loudness never decides line identity.
import subprocess, wave, io, struct
import numpy as np
from scipy import signal, ndimage

SRC = 'Audio_8bit琵琶曲.m4s'
SR, HOP = 22050, 512
FFMPEG = r'E:\ffmpeg-8.1.2-essentials_build\bin\ffmpeg.exe'
BPM = 71.0
PEAK_MIN = 0.20            # absolute peak threshold (global-normalized salience)
MAX_PEAKS = 6
MAX_LINES = 4

raw = subprocess.run([FFMPEG, '-v', 'error', '-i', SRC, '-ac', '1', '-ar', str(SR),
                      '-f', 's16le', '-'], capture_output=True).stdout
data = np.frombuffer(raw, np.int16).astype(np.float64) / 32768.0

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

midis = np.arange(40, 93)
M = np.vstack([semitone_mag(m) for m in midis])
S0 = M.copy()
for h, wgt in [(2, 0.84), (3, 0.70), (4, 0.60), (5, 0.50), (6, 0.42), (7, 0.36), (8, 0.30)]:
    S0 += wgt * ndimage.shift(M, (12 * np.log2(h), 0), order=1, mode='constant', cval=0.0)
S0 = ndimage.uniform_filter1d(S0, 3, axis=1)
REF = float(np.percentile(S0.max(axis=0), 90))
S_norm = S0 / (REF + 1e-9)

# ---------- frame-wise peak picking (local maxima on pitch axis) ----------
peaks = []
for i in range(nframes):
    col = S_norm[:, i]
    found = []
    for j in range(1, len(col) - 1):
        if col[j] > col[j - 1] and col[j] >= col[j + 1] and col[j] > PEAK_MIN:
            a, b, c = col[j - 1], col[j], col[j + 1]
            den = a - 2 * b + c
            shift = 0.5 * (a - c) / den if den != 0 else 0.0
            found.append((midis[j] + shift, col[j]))
    found.sort(key=lambda x: -x[1])
    peaks.append(found[:MAX_PEAKS])

# ---------- candidate notes per pitch (contiguous frames, 1-frame gap allowed) ----------
cands = {}
for i, ps in enumerate(peaks):
    for (p, s) in ps:
        key = int(round(p))
        lst = cands.setdefault(key, [])
        if lst and i - lst[-1][1] <= 2:
            lst[-1][1] = i
            lst[-1][2].append(s)
        else:
            lst.append([i, i, [s]])
notes = []
for key, lst in cands.items():
    for (a, b, ss) in lst:
        strong = max(ss) > 0.45
        if b - a + 1 >= 2 or strong:
            notes.append((a, b, key, max(ss)))
notes.sort(key=lambda x: x[0])
print('candidate notes: %d' % len(notes))

# ---------- greedy continuity line tracking ----------
lines = []   # [last_end, last_pitch, notes[]]
dropped = 0
for (a, b, p, s) in notes:
    best, bestcost = -1, 1e9
    for li, L in enumerate(lines):
        gap = a - L[0]                              # frames; negative = would overlap
        pcost = min(abs(p - L[1]), 24)
        cost = pcost
        if gap < -2: cost += 6
        elif gap > 12: cost += 4 + (gap - 12) * 0.3
        if cost < bestcost:
            bestcost, best = cost, li
    newcost = 9.0 if len(lines) < MAX_LINES else 1e9
    if newcost < bestcost:
        lines.append([b, p, [(a, b, p)]])
    elif best is not None and bestcost <= 14:
        L = lines[best]
        L[2].append((a, b, p))
        L[0] = max(L[0], b)
        L[1] = p
    else:
        dropped += 1
print('lines: %d, dropped: %d' % (len(lines), dropped))
for li, L in enumerate(lines):
    ps = [p for (a, b, p) in L[2]]
    print('  line %d: %d notes, median pitch %.0f, span %.1fs'
          % (li + 1, len(ps), np.median(ps), (L[0] * frame_ms) / 1000))

# ---------- roles by median pitch, fold to bands ----------
meds = [float(np.median([p for (a, b, p) in L[2]])) if L[2] else 0 for L in lines]
order = sorted(range(len(lines)), key=lambda k: -meds[k])
BANDS = {0: (62, 86), 1: (57, 81), 2: (52, 76), 3: (38, 58)}
def fold(p, lo, hi):
    while p > hi: p -= 12
    while p < lo: p += 12
    return p

voices = [[], [], [], []]
for rank, li in enumerate(order[:4]):
    vi = rank
    lo, hi = BANDS[vi]
    out = []
    for (a, b, p) in sorted(lines[li][2]):
        t, d, p2 = a * frame_ms, (b - a + 1) * frame_ms, fold(p, lo, hi)
        if out and t < out[-1][0] + out[-1][1]:
            out[-1] = (out[-1][0], t - out[-1][0], out[-1][2])
            if out[-1][1] < 40: out.pop()
        out.append((t, d, p2))
    voices[vi] = out
    ps = [p for (t, d, p) in out]
    iv = np.abs(np.diff(ps)) if len(ps) > 1 else np.array([0])
    print('V%d: %d notes, interval p50=%.0f p90=%.0f, >7sem %.0f%%'
          % (vi + 1, len(ps), np.percentile(iv, 50), np.percentile(iv, 90), (iv > 7).mean() * 100))

# ---------- rhythm quantization + sequential encode ----------
grid = 60.0 / BPM / 4 * 1000
def encode(lst):
    seq = []
    cur = 0
    for (t, d, p) in sorted(lst):
        ts = round(t / grid) * grid
        dq = max(round(d / grid) * grid, grid * 0.5)
        gap = int(round((ts - cur) / 25) * 25)
        if gap >= 100: seq.append((0, gap))
        seq.append((round(440.0 * 2 ** ((p - 69) / 12)), max(75, int(round(dq / 25) * 25))))
        cur = ts + dq
    while seq and seq[-1][0] == 0: seq.pop()
    return seq

seqs = [encode(v) for v in voices]
for vi, s in enumerate(seqs):
    print('V%d: %d entries, %.1fs' % (vi + 1, len(s), sum(x[1] for x in s) / 1000))

# ---------------- MIDI ----------------
TPQ = 480
us_q = int(60e6 / BPM)
def varlen(n):
    b = [n & 0x7F]; n >>= 7
    while n:
        b.append((n & 0x7F) | 0x80); n >>= 7
    return bytes(reversed(b))

def track_chunk(events):
    d = b''; last = 0
    for tick, ev in events:
        d += varlen(tick - last) + ev; last = tick
    return b'MTrk' + struct.pack('>I', len(d) + 4) + d + b'\x00\xff\x2f\x00'

def ms2tick(ms):
    return int(round(ms / 1000.0 * 1e6 / us_q * TPQ))

tracks = [track_chunk([(0, b'\xff\x51\x03' + struct.pack('>I', us_q)[1:]),
                       (0, b'\xff\x03\x0bTrack Tempo')])]
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

# ---------------- preview ----------------
def synth(path):
    total = max(sum(x[1] for x in s) for s in seqs)
    buf = np.zeros(int(total / 1000 * SR) + SR // 4)
    G = [0.28, 0.10, 0.08, 0.16]
    for vi, s in enumerate(seqs):
        pos = 0
        for freq, ms in s:
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

synth('tools/preview_pipa8.wav')
print('preview written')

# ---------------- Song2.c/h + Stm32Melody2.java ----------------
names = ['S2_V1', 'S2_V2', 'S2_V3', 'S2_V4']
defs = []
for vi, s in enumerate(seqs):
    rows = ',\n'.join('    {%d, %d}' % (f_, m) for f_, m in s)
    defs.append('const uint16_t %s[][2] = {\n%s\n};\nconst uint16_t %s_Len = sizeof(%s) / sizeof(%s[0]);'
                % (names[vi], rows, names[vi], names[vi], names[vi]))
io.open('Stm32Link_Keil/Hardware/Song2.c', 'w', encoding='ascii').write(
    '''#include "Song2.h"

// Auto-generated by tools/chiptune_to_mid2.py (8-bit pipa, continuity tracking) - do not edit.
// Each entry: {frequency in Hz (0 = rest), duration in ms}.
%s

''' % '\n\n'.join(defs))
io.open('Stm32Link_Keil/Hardware/Song2.h', 'w', encoding='ascii').write('''#ifndef __SONG2_H
#define __SONG2_H

#include "stm32f10x.h"

// Auto-generated by tools/chiptune_to_mid2.py (8-bit pipa) - do not edit.
extern const uint16_t S2_V1[][2];
extern const uint16_t S2_V1_Len;
extern const uint16_t S2_V2[][2];
extern const uint16_t S2_V2_Len;
extern const uint16_t S2_V3[][2];
extern const uint16_t S2_V3_Len;
extern const uint16_t S2_V4[][2];
extern const uint16_t S2_V4_Len;

#endif
''')

def jnum(x):
    return ('%d.0f' % x) if x else '0.0f'
blocks = []
for vi, s in enumerate(seqs):
    rows = ',\n'.join('            {%s, %d}' % (jnum(f_), m) for f_, m in s)
    blocks.append('        {\n%s\n        }' % rows)
io.open('with_stm32/src/main/java/qw/with_stm32/Stm32Melody2.java', 'w', encoding='ascii').write(
    '''package qw.with_stm32;

// Auto-generated by tools/chiptune_to_mid2.py (8-bit pipa, continuity tracking) - do not edit.
// VOICES[0..3] = {melody, harmony, filler, bass}; each note {frequency Hz (0=rest), duration ms}.
public final class Stm32Melody2 {
    public static final int NUM_VOICES = 4;
    public static final float[][][] VOICES = {
%s
    };

    private Stm32Melody2() {}
}
''' % ',\n'.join(blocks))
print('Song2.c/h + Stm32Melody2.java written')
