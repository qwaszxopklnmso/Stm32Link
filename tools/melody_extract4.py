# Melody extraction v4 — v3 + fixes for sparseness:
#   * comb-filter tempo detection over 60..200 BPM (no more half/double tempo errors)
#   * sixteenth-note grid (was eighth) so fast runs/tremolo survive
#   * short notes kept (min 2 frames), same-pitch merge only for gaps < 60ms
#   * lighter Viterbi smoothing (fast melodic movement allowed)
#   * pluck-envelope preview (much easier to judge than raw square)
#   * writes 4 candidate previews (0s/30s/60s/90s) for the user to choose from
import json, wave, io, sys
import numpy as np
from scipy import signal, ndimage

SR = 22050
NFFT = 8192
HOP = 512
MIDI_LO, MIDI_HI = 52, 88
SRC = 'tools/song_full.wav'

with wave.open(SRC, 'rb') as w:
    data = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float64) / 32768.0

f, t, Z = signal.stft(data, fs=SR, nperseg=4096, noverlap=4096 - HOP)
mag = np.abs(Z)
Hmag = ndimage.median_filter(mag, size=(1, 17))
Pmag = ndimage.median_filter(mag, size=(17, 1))
mask = (Hmag ** 2) / (Hmag ** 2 + Pmag ** 2 + 1e-10)
H = Hmag * mask
nframes = H.shape[1]
frame_ms = HOP * 1000.0 / SR
fps = SR / HOP

# ---------- semitone spectrogram + harmonic salience ----------
bin_hz = SR / NFFT
def semitone_mag(m):
    freq = 440.0 * 2 ** ((m - 69) / 12)
    pos = freq / bin_hz
    i0 = int(np.floor(pos)); frac = pos - i0
    return H[i0, :] * (1 - frac) + H[i0 + 1, :] * frac

midis = np.arange(MIDI_LO, MIDI_HI + 1)
M = np.vstack([semitone_mag(m) for m in midis])
S = M.copy()
for h, wgt in [(2, 0.84), (3, 0.70), (4, 0.60), (5, 0.50), (6, 0.42), (7, 0.36), (8, 0.30)]:
    S += wgt * ndimage.shift(M, (12 * np.log2(h), 0), order=1, mode='constant', cval=0.0)
S = ndimage.uniform_filter1d(S, 3, axis=1)
S = S / (S.max(axis=0, keepdims=True) + 1e-9)

# ---------- Viterbi (light smoothing) ----------
nmidi = len(midis)
UV = -1
nstates = nmidi + 1
EMIT_UV = 0.30
MOVE_COST = 0.06
SWITCH_COST = 0.7

emit = np.zeros((nframes, nstates))
emit[:, :nmidi] = np.clip(S.T, 0, 1)
voiced_energy = S.max(axis=0)
emit[:, :nmidi] = np.where(voiced_energy[:, None] > 0.10, emit[:, :nmidi], 0.0)
emit[:, nmidi] = EMIT_UV

dp = np.full((nframes, nstates), -1e18)
bp = np.zeros((nframes, nstates), dtype=np.int32)
dp[0] = emit[0]
prev = np.arange(nstates)[None, :]
cost = np.abs(prev.T - prev) * MOVE_COST
cost[:, UV] = SWITCH_COST
cost[UV, :] = SWITCH_COST
cost[UV, UV] = 0.0
cost[:nmidi, :nmidi][np.diag_indices(nmidi)] = 0.0
for i in range(1, nframes):
    total = dp[i - 1][:, None] - cost
    bp[i] = np.argmax(total, axis=0)
    dp[i] = total[bp[i], np.arange(nstates)] + emit[i]

path = np.zeros(nframes, dtype=np.int32)
path[-1] = np.argmax(dp[-1])
for i in range(nframes - 1, 0, -1):
    path[i - 1] = bp[i, path[i]]
track = np.where(path < nmidi, midis[np.clip(path, 0, nmidi - 1)], -1)

# ---------- tempo via comb filter (use PERCUSSIVE component: the kick is tempo truth in DJ tracks) ----------
def comb_bpm(onset_env, lo=60.0, hi=200.0):
    best = (0, 120.0)
    for bpm in np.arange(lo, hi + 0.01, 0.5):
        P = 60.0 / bpm * fps
        nbeats = int(len(onset_env) / P)
        if nbeats < 8:
            continue
        prof = np.zeros(int(np.ceil(P)) + 1)
        for i in range(nbeats):
            seg = onset_env[int(i * P): int((i + 1) * P) + 1]
            prof[:len(seg)] += seg
        prof /= nbeats
        if prof.max() > best[0]:
            best = (prof.max(), bpm)
    return best

def onset_env_from(spec):
    fl = np.diff(spec, axis=1)
    fl[fl < 0] = 0
    env = fl.sum(axis=0)
    env = env - ndimage.uniform_filter1d(env, 43)
    return np.maximum(env, 0)

onset = onset_env_from(M)
fmax_bin = int(4000 / bin_hz)
Pc = (Pmag * (1 - mask))[:fmax_bin, :]
onset_p = onset_env_from(Pc)

score_h, bpm_h = comb_bpm(onset)
score_p, bpm_p = comb_bpm(onset_p)
use_env = onset_p if score_p > 0.3 * score_h else onset
score_u, bpm_u = comb_bpm(use_env)
bpm = bpm_u
# octave disambiguation: if the double tempo combs at >=75% of the winner, prefer faster
if bpm < 95 and bpm * 2 <= 200:
    s2, bpm2 = comb_bpm(use_env, lo=bpm * 2 * 0.97, hi=bpm * 2 * 1.03)
    if s2 >= 0.75 * score_u:
        bpm = bpm2
beat_s = 60.0 / bpm
grid = beat_s * 1000 / 8          # 32nd-note grid = 2x detail of sixteenth, no drift risk
print('tempo: harmonic %.0f / percussive %.0f BPM -> using %.0f, grid = %.0f ms'
      % (bpm_h, bpm_p, bpm, grid))

# ---------- track -> raw notes ----------
raw = []
i = 0
while i < nframes:
    if track[i] >= 0:
        m0 = track[i]
        j = i
        while j < nframes and track[j] == m0:
            j += 1
        raw.append([int(m0), i * frame_ms, (j - i) * frame_ms])
        i = j
    else:
        i += 1

# heal Viterbi flicker at RAW level: same-pitch runs separated by <=2 unvoiced frames
healed = []
for m, ts, d in raw:
    if healed and healed[-1][0] == m:
        prev_end = healed[-1][1] + healed[-1][2]
        if ts - prev_end <= 2 * frame_ms:
            healed[-1][2] = ts + d - healed[-1][1]
            continue
    healed.append([m, ts, d])
raw = healed

# quantize each raw run independently — NO same-pitch merging here (preserves tremolo)
quant = []
for m, ts, d in raw:
    if d < 2 * frame_ms:
        continue
    ts_q = round(ts / grid) * grid
    d_q = max(round(d / grid) * grid, grid * 0.5)
    if quant and abs(ts_q - quant[-1][1]) < grid * 0.4 and quant[-1][0] == m:
        continue                    # rounded onto the same slot as previous note
    quant.append([m, ts_q, d_q])
for a, b in zip(quant, quant[1:]):
    if a[1] + a[2] > b[1]:
        a[2] = b[1] - a[1]
quant = [x for x in quant if x[2] >= 45]

# ---------- scale snapping ----------
pc = np.zeros(12)
for m, ts, d in quant:
    pc[m % 12] += d
scales = {'major': [0, 2, 4, 5, 7, 9, 11], 'minor': [0, 2, 3, 5, 7, 8, 10],
          'pentaM': [0, 2, 4, 7, 9], 'pentaN': [0, 3, 5, 7, 10]}
best_s = (0, None, None, None)
for root in range(12):
    for name, iv in scales.items():
        members = {(root + x) % 12 for x in iv}
        score = sum(d for m, ts, d in quant if m % 12 in members) / max(1, sum(x[2] for x in quant))
        if score > best_s[0]:
            best_s = (score, root, sorted(members), name)
inscale, root, members, sname = best_s
print('key: %s %s (%.0f%%)' % (['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B'][root], sname, inscale * 100))

def snap_to_scale(m):
    if m % 12 in members:
        return m
    for off in (1, -1, 2, -2, 3, -3, 4, -4):
        if (m + off) % 12 in members:
            return m + off
    return m

final = []
for m, ts, d in quant:
    m2 = snap_to_scale(m)
    final.append([m2, ts, d])

# ---------- octave folding toward melody center ----------
w = [d for m, ts, d in final]
med = float(np.average([m for m, ts, d in final], weights=w)) if final else 69.0
folded = []
for m, ts, d in final:
    while m - med > 9:
        m -= 12
    while med - m > 9:
        m += 12
    folded.append([m, ts, d])
final = folded
print('melody center: midi %.1f, total notes: %d' % (med, len(final)))

# ---------- window cut + sequential output ----------
def notes_in(start_s, length_s=55):
    res = []
    cur = start_s * 1000
    for m, ts, d in final:
        if ts < start_s * 1000 or ts >= (start_s + length_s) * 1000:
            continue
        d = int(round(d / 25) * 25)
        if d < 50:
            continue
        gap = int(round((ts - cur) / 25) * 25)
        if gap >= 75:
            res.append({'m': 0, 'f': 0, 'd': gap})
        res.append({'m': m, 'f': round(440.0 * 2 ** ((m - 69) / 12), 1), 'd': d})
        cur = ts + d
    return res

def gen_preview(seq, path):
    total = sum(o['d'] for o in seq)
    buf = np.zeros(int(total / 1000 * SR) + SR // 4)
    pos = 0
    for o in seq:
        n = int(o['d'] / 1000 * SR)
        if o['m']:
            tt = np.arange(n) / SR
            env = np.minimum(tt / 0.004, 1) * np.exp(-2.2 * tt / max(o['d'] / 1000, 0.05))
            sig = np.sign(np.sin(2 * np.pi * o['f'] * tt)) + 0.35 * np.sin(2 * np.pi * o['f'] * 2 * tt)
            buf[pos:pos + n] += 0.3 * sig * env
        pos += n
    peak = np.abs(buf).max()
    if peak > 0:
        buf = buf / peak * 0.8
    with wave.open(path, 'wb') as wv:
        wv.setnchannels(1); wv.setsampwidth(2); wv.setframerate(SR)
        wv.writeframes((buf * 32767).astype(np.int16).tobytes())

for start in [0, 30, 60, 90]:
    seq = notes_in(start)
    dens = sum(1 for o in seq if o['m']) / 55.0
    print('window %2ds: %d notes (%.1f/s), rest %.1fs' %
          (start, sum(1 for o in seq if o['m']), dens, sum(o['d'] for o in seq if not o['m']) / 1000))
    gen_preview(seq, 'tools/preview_%ds.wav' % start)

# ---------- generate code from the auto-best window (most notes) ----------
best_start = max([0, 30, 60, 90], key=lambda s: sum(1 for o in notes_in(s) if o['m']))
out = notes_in(best_start)
print('auto-best window: %ds' % best_start)

rows = ',\n'.join('    {%d, %d}' % (o['f'] if o['m'] else 0, o['d']) for o in out)
io.open('Stm32Link_Keil/Hardware/Song.c', 'w', encoding='ascii').write(
    '''#include "Song.h"

// Auto-generated by tools/melody_extract4.py (pipa-dj song) - do not edit.
// Each entry: {frequency in Hz (0 = rest), duration in ms}.
const uint16_t Song_Notes[][2] = {
%s
};
const uint16_t Song_Len = sizeof(Song_Notes) / sizeof(Song_Notes[0]);
''' % rows)

java_rows = ',\n'.join('            {%sf, %d}' % (('0' if not o['m'] else str(o['f'])), o['d']) for o in out)
io.open('with_stm32/src/main/java/qw/with_stm32/Stm32Melody.java', 'w', encoding='ascii').write(
    '''package qw.with_stm32;

// Auto-generated by tools/melody_extract4.py (pipa-dj song) - do not edit.
// {frequency in Hz (0 = rest), duration in ms}, synchronized with the STM32 Song_Notes array.
public final class Stm32Melody {
    public static final float[][] NOTES = {
%s
    };

    private Stm32Melody() {}
}
''' % java_rows)
with open('tools/melody.json', 'w', encoding='utf-8') as fp:
    json.dump(out, fp)
print('Song.c + Stm32Melody.java + 4 previews written')
