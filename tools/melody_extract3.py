# Melody extraction v3: semitone spectrogram + harmonic salience + Viterbi tracking
# + tempo/rhythm quantization + musical-scale snapping + best-window selection.
# Much more robust on dense DJ mixes than per-frame autocorrelation.
import json, wave, io
import numpy as np
from scipy import signal, ndimage

SR = 22050
NFFT = 8192
HOP = 512
MIDI_LO, MIDI_HI = 52, 88        # E3..E6 melody band (skips bass < 160Hz)
SRC = 'tools/song_full.wav'

# ---------- load + HPSS ----------
with wave.open(SRC, 'rb') as w:
    assert w.getframerate() == SR
    data = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float64) / 32768.0

f, t, Z = signal.stft(data, fs=SR, nperseg=4096, noverlap=4096 - HOP)
mag = np.abs(Z)
Hmag = ndimage.median_filter(mag, size=(1, 17))
Pmag = ndimage.median_filter(mag, size=(17, 1))
mask = (Hmag ** 2) / (Hmag ** 2 + Pmag ** 2 + 1e-10)
H = Hmag * mask          # harmonic-component magnitude, shape (freq, frames)
nframes = H.shape[1]
frame_ms = HOP * 1000.0 / SR

# ---------- semitone spectrogram (interpolated from linear bins) ----------
bin_hz = SR / NFFT
def semitone_mag(m):   # magnitude at midi note m (float ok)
    freq = 440.0 * 2 ** ((m - 69) / 12)
    pos = freq / bin_hz
    i0 = int(np.floor(pos))
    frac = pos - i0
    return H[i0, :] * (1 - frac) + H[i0 + 1, :] * frac

midis = np.arange(MIDI_LO, MIDI_HI + 1)
M = np.vstack([semitone_mag(m) for m in midis])       # (nmidi, nframes)

# ---------- harmonic salience ----------
S = M.copy()
for h, wgt in [(2, 0.84), (3, 0.70), (4, 0.60), (5, 0.50), (6, 0.42), (7, 0.36), (8, 0.30)]:
    S += wgt * ndimage.shift(M, (12 * np.log2(h), 0), order=1, mode='constant', cval=0.0)

# mild temporal smoothing
S = ndimage.uniform_filter1d(S, 3, axis=1)

# normalize per frame
S = S / (S.max(axis=0, keepdims=True) + 1e-9)

# ---------- Viterbi: melody trajectory ----------
nmidi = len(midis)
UV = -1                                     # unvoiced state
nstates = nmidi + 1
EMIT_UV = 0.35
MOVE_COST = 0.10                            # per semitone
SWITCH_COST = 0.9                           # voiced <-> unvoiced

emit = np.zeros((nframes, nstates))
emit[:, :nmidi] = np.clip(S.T, 0, 1)
voiced_energy = S.max(axis=0)
emit[:, :nmidi] = np.where(voiced_energy[:, None] > 0.12, emit[:, :nmidi], 0.0)
emit[:, nmidi] = EMIT_UV

dp = np.full((nframes, nstates), -1e18)
bp = np.zeros((nframes, nstates), dtype=np.int32)
dp[0] = emit[0]
prev = np.arange(nstates)[None, :]
for i in range(1, nframes):
    cost = np.abs(prev.T - prev) * MOVE_COST          # (from,to) semitone distance
    # voiced<->unvoiced switching cost
    cost[:, UV] = SWITCH_COST
    cost[UV, :] = SWITCH_COST
    cost[UV, UV] = 0.0
    cost[:nmidi, :nmidi][np.diag_indices(nmidi)] = 0.0
    total = dp[i - 1][:, None] - cost
    bp[i] = np.argmax(total, axis=0)
    dp[i] = total[bp[i], np.arange(nstates)] + emit[i]

path = np.zeros(nframes, dtype=np.int32)
path[-1] = np.argmax(dp[-1])
for i in range(nframes - 1, 0, -1):
    path[i - 1] = bp[i, path[i]]

track = np.where(path < nmidi, midis[np.clip(path, 0, nmidi - 1)], -1)

# ---------- onset envelope & tempo ----------
flux = np.diff(M, axis=1)
flux[flux < 0] = 0
onset = flux.sum(axis=0)
onset = onset - ndimage.uniform_filter1d(onset, 43)   # remove slow drift (~1s)
ac = np.correlate(onset, onset, mode='full')[len(onset) - 1:]
# search 70..160 BPM directly (avoids the classic half/double-tempo octave error)
min_lag = int(0.375 / (HOP / SR))
max_lag = int(0.857 / (HOP / SR))
k = int(np.argmax(ac[min_lag:max_lag])) + min_lag
if k // 2 >= min_lag and ac[k // 2] > 0.85 * ac[k]:
    k = k // 2                                        # prefer the faster tempo when comparable
beat_s = k * HOP / SR
eighth_s = beat_s / 2
print('tempo: %.0f BPM (beat %.0f ms)' % (60 / beat_s, beat_s * 1000))

# ---------- track -> notes ----------
notes = []
i = 0
while i < nframes:
    if track[i] >= 0:
        m0 = track[i]
        j = i
        while j < nframes and track[j] == m0:
            j += 1
        notes.append([int(m0), i * frame_ms, (j - i) * frame_ms])
        i = j
    else:
        i += 1

# drop tiny notes, then quantize rhythm to eighth grid
grid = max(eighth_s * 1000, 100)
quant = []
for m, ts, d in notes:
    if d < grid * 0.6:
        continue
    ts_q = round(ts / grid) * grid
    d_q = max(grid, round(d / grid) * grid)
    if quant and quant[-1][0] == m and abs(quant[-1][1] + quant[-1][2] - ts_q) < grid * 0.5:
        quant[-1][2] += d_q                       # merge split same-pitch notes
    else:
        quant.append([m, ts_q, d_q])
for a, b in zip(quant, quant[1:]):
    if a[1] + a[2] > b[1]:
        a[2] = b[1] - a[1]                        # no overlap

# ---------- scale snapping ----------
pc = np.zeros(12)
for m, ts, d in quant:
    pc[m % 12] += d
scales = {'major': [0, 2, 4, 5, 7, 9, 11], 'minor': [0, 2, 3, 5, 7, 8, 10],
          'pentaM': [0, 2, 4, 7, 9], 'pentaN': [0, 3, 5, 7, 10]}
best = (0, None, None, None)
for root in range(12):
    for name, iv in scales.items():
        members = {(root + x) % 12 for x in iv}
        score = sum(d for m, ts, d in quant if m % 12 in members) / max(1, sum(x[2] for x in quant))
        if score > best[0]:
            best = (score, root, sorted(members), name)
inscale, root, members, name = best
print('key: %s %s, in-scale %.0f%%' % (['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B'][root], name, inscale * 100))

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
    if final and final[-1][0] == m2 and abs(final[-1][1] + final[-1][2] - ts) < grid * 0.5:
        final[-1][2] += d
    else:
        final.append([m2, ts, d])

# ---------- octave folding toward the melody's center ----------
pitched = [m for m, ts, d in final]
weights = [d for m, ts, d in final]
med = float(np.average(pitched, weights=weights)) if pitched else 69.0
folded = []
for m, ts, d in final:
    while m - med > 9:
        m -= 12
    while med - m > 9:
        m += 12
    folded.append([m, ts, d])
# re-merge neighbours after folding
final = []
for m, ts, d in folded:
    if final and final[-1][0] == m and abs(final[-1][1] + final[-1][2] - ts) < grid * 0.5:
        final[-1][2] += d
    else:
        final.append([m, ts, d])
print('melody center: midi %.1f' % med)

# ---------- best window selection ----------
wins = []
for start_s in [0, 30, 60, 90, 120]:
    end_s = start_s + 55
    cov = sum(d for m, ts, d in final if start_s <= ts / 1000 < end_s) / 55000.0
    wins.append((cov, start_s))
wins.sort(reverse=True)
best_cov, start_s = wins[0]
print('window: %d-%ds (coverage %.0f%%)' % (start_s, start_s + 55, best_cov * 100))

# sequential list with explicit rests (buzzer/MC play entries back-to-back)
seq = []
cur_ms = start_s * 1000
for m, ts, d in final:
    if ts / 1000 < start_s or ts / 1000 >= start_s + 55:
        continue
    d = int(round(d / 25) * 25)
    if d < 50:
        continue
    gap = int(round((ts - cur_ms) / 25) * 25)
    if gap >= 75:
        seq.append({'m': 0, 'f': 0, 'd': gap})
    seq.append({'m': m, 'f': round(440.0 * 2 ** ((m - 69) / 12), 1), 'd': d})
    cur_ms = ts + d
out = seq
print('notes:', len(out), 'pitched:', sum(1 for o in out if o['m']),
      'rest %.1fs' % (sum(o['d'] for o in out if not o['m']) / 1000))
print('first 30:', [(o['m'], o['d']) for o in out[:30]])

with open('tools/melody.json', 'w', encoding='utf-8') as fp:
    json.dump(out, fp)

# ---------- preview wav (what the buzzer will play) ----------
total = sum(o['d'] for o in out)
buf = np.zeros(int(total / 1000 * SR) + SR // 4)
pos = 0
for o in out:
    n = int(o['d'] / 1000 * SR)
    if o['m']:
        tt = np.arange(n) / SR
        env = np.minimum(1, tt / 0.008) * np.minimum(1, (o['d'] / 1000 - tt) / 0.02)
        buf[pos:pos + n] += 0.4 * np.sign(np.sin(2 * np.pi * o['f'] * tt)) * env
    pos += n
peak = np.abs(buf).max()
if peak > 0:
    buf = buf / peak * 0.8
with wave.open('tools/melody_preview.wav', 'wb') as w:
    w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR)
    w.writeframes((buf * 32767).astype(np.int16).tobytes())

# ---------- generate Song.c / Stm32Melody.java ----------
rows = ',\n'.join('    {%d, %d}' % (o['f'] if o['m'] else 0, o['d']) for o in out)
song_c = '''#include "Song.h"

// Auto-generated by tools/melody_extract3.py (pipa-dj song, salience+Viterbi) - do not edit.
// Each entry: {frequency in Hz (0 = rest), duration in ms}.
const uint16_t Song_Notes[][2] = {
%s
};
const uint16_t Song_Len = sizeof(Song_Notes) / sizeof(Song_Notes[0]);
''' % rows
io.open('Stm32Link_Keil/Hardware/Song.c', 'w', encoding='ascii').write(song_c)

java_rows = ',\n'.join('            {%sf, %d}' % (('0' if not o['m'] else str(o['f'])), o['d']) for o in out)
java = '''package qw.with_stm32;

// Auto-generated by tools/melody_extract3.py (pipa-dj song) - do not edit.
// {frequency in Hz (0 = rest), duration in ms}, synchronized with the STM32 Song_Notes array.
public final class Stm32Melody {
    public static final float[][] NOTES = {
%s
    };

    private Stm32Melody() {}
}
''' % java_rows
io.open('with_stm32/src/main/java/qw/with_stm32/Stm32Melody.java', 'w', encoding='ascii').write(java)
print('Song.c + Stm32Melody.java + preview written')
