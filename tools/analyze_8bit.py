# Analyze the 8-bit pipa m4s: is it clean chiptune? how many voices? tempo? melody coherence?
# Diagnostics only - does NOT touch Song.c / Stm32Melody.java.
import subprocess, wave, io
import numpy as np
from scipy import signal, ndimage

SRC = 'Audio_8bit琵琶曲.m4s'
SR, HOP = 22050, 512
FFMPEG = r'E:\ffmpeg-8.1.2-essentials_build\bin\ffmpeg.exe'

raw = subprocess.run([FFMPEG, '-v', 'error', '-i', SRC, '-ac', '1', '-ar', str(SR),
                      '-f', 's16le', '-'], capture_output=True).stdout
data = np.frombuffer(raw, np.int16).astype(np.float64) / 32768.0
print('duration %.1fs' % (len(data) / SR))

# ---------- HPSS ----------
f, t, Z = signal.stft(data, fs=SR, nperseg=4096, noverlap=4096 - HOP)
mag = np.abs(Z)
Hm = ndimage.median_filter(mag, size=(1, 17))
Pm = ndimage.median_filter(mag, size=(17, 1))
mask = (Hm ** 2) / (Hm ** 2 + Pm ** 2 + 1e-10)
H = Hm * mask
nframes = H.shape[1]

# ---------- harmonic flatness / squareness check ----------
# square waves have odd-harmonic energy (h=3,5,7) much stronger than even (2,4,6)
def band_energy(spec, f_lo, f_hi):
    b = (f >= f_lo) & (f <= f_hi)
    return (spec[b] ** 2).sum(axis=0)

e2 = band_energy(Hm, 800, 1200)    # ~2nd harmonic zone of 400Hz fundamental
e3 = band_energy(Hm, 1200, 2000)   # 3rd-5th zone
even_odd = e3 / (e2 + 1e-9)
print('odd/even harmonic energy ratio: p50=%.2f (square-wave-ish if >1)' % np.median(even_odd))

# spectral flux sharpness (chiptune onsets are razor sharp)
flux = np.diff(mag, axis=1)
flux[flux < 0] = 0
onset_all = flux.sum(axis=0)
print('onset peak density: %.1f/s' % ((onset_all > np.percentile(onset_all, 90)).sum() / (len(data) / SR)))

# ---------- semitone salience ----------
bin_hz = SR / 8192
def semitone_mag(m):
    freq = 440.0 * 2 ** ((m - 69) / 12)
    pos = freq / bin_hz
    i0 = int(np.floor(pos)); frac = pos - i0
    return H[i0, :] * (1 - frac) + H[i0 + 1, :] * frac

midis = np.arange(52, 89)
M = np.vstack([semitone_mag(m) for m in midis])
S = M.copy()
for h, wgt in [(2, 0.84), (3, 0.70), (4, 0.60), (5, 0.50), (6, 0.42), (7, 0.36), (8, 0.30)]:
    S += wgt * ndimage.shift(M, (12 * np.log2(h), 0), order=1, mode='constant', cval=0.0)
S = ndimage.uniform_filter1d(S, 3, axis=1)
S = S / (S.max(axis=0, keepdims=True) + 1e-9)

# ---------- polyphony estimate: strong peaks per frame ----------
peaks_per_frame = (S > 0.55).sum(axis=0)
print('polyphony (salience>0.55 peaks/frame): p50=%.0f p90=%.0f' %
      tuple(np.percentile(peaks_per_frame, [50, 90])))

# ---------- tempo comb ----------
fl = np.diff(M, axis=1); fl[fl < 0] = 0
onset = np.maximum(fl.sum(axis=0) - ndimage.uniform_filter1d(fl.sum(axis=0), 43), 0)
fps = SR / HOP
best = (0, 120.0)
for bpm in np.arange(60, 200.5, 0.5):
    P = 60.0 / bpm * fps
    n = int(len(onset) / P)
    if n < 8: continue
    prof = np.zeros(int(np.ceil(P)) + 1)
    for i in range(n):
        seg = onset[int(i * P): int((i + 1) * P) + 1]
        prof[:len(seg)] += seg
    prof /= n
    if prof.max() > best[0]: best = (prof.max(), bpm)
print('tempo: %.0f BPM' % best[1])

# ---------- melody Viterbi (single line) coherence check ----------
nmidi = len(midis); UV = -1; nstates = nmidi + 1
emit = np.zeros((nframes, nstates))
emit[:, :nmidi] = np.clip(S.T, 0, 1)
ve = S.max(axis=0)
emit[:, :nmidi] = np.where(ve[:, None] > 0.10, emit[:, :nmidi], 0.0)
emit[:, nmidi] = 0.30
cost = np.abs(np.arange(nstates)[None, :].T - np.arange(nstates)[None, :]) * 0.06
cost[:, UV] = 0.7; cost[UV, :] = 0.7; cost[UV, UV] = 0.0
cost[:nmidi, :nmidi][np.diag_indices(nmidi)] = 0.0
dp = np.full((nframes, nstates), -1e18); bp = np.zeros((nframes, nstates), dtype=np.int32)
dp[0] = emit[0]
for i in range(1, nframes):
    tot = dp[i - 1][:, None] - cost
    bp[i] = np.argmax(tot, axis=0)
    dp[i] = tot[bp[i], np.arange(nstates)] + emit[i]
path = np.zeros(nframes, dtype=np.int32); path[-1] = np.argmax(dp[-1])
for i in range(nframes - 1, 0, -1):
    path[i - 1] = bp[i, path[i]]
track = np.where(path < nmidi, midis[np.clip(path, 0, nmidi - 1)], -1)

runs = []
i = 0
while i < nframes:
    if track[i] >= 0:
        j = i
        while j < nframes and track[j] == track[i]: j += 1
        if j - i >= 2: runs.append((i, j, track[i]))
        i = j
    else: i += 1
pitches = [r[2] for r in runs]
iv = np.abs(np.diff(pitches))
print('melody line: %d notes (%.1f/s), interval p50=%.0f p90=%.0f, >7sem %.0f%%' %
      (len(runs), len(runs) / (len(data) / SR),
       np.percentile(iv, 50) if len(iv) else 0, np.percentile(iv, 90) if len(iv) else 0,
       (iv > 7).mean() * 100 if len(iv) else 0))
u, c = np.unique([p % 12 for p in pitches], return_counts=True)
names = ['C','C#','D','D#','E','F','F#','G','G#','A','A#','B']
print('pitch classes:', [(names[k], int(n)) for n, k in sorted(zip(c.tolist(), u.tolist()), reverse=True)[:6]])
