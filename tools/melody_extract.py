# Extract melody notes from song.wav (mono, 22050Hz) via autocorrelation pitch tracking.
# Output: tools/melody.json  [{f: hz, d: ms, m: midi}, ...]
import json, wave, sys
import numpy as np

SR = 22050
WIN = 2048
HOP = 512
FMIN, FMAX = 150.0, 1100.0

def read_wav(path):
    with wave.open(path, 'rb') as w:
        assert w.getframerate() == SR and w.getnchannels() == 1
        data = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
    return data.astype(np.float64) / 32768.0

def autocorr_pitch(frame):
    # normalized autocorrelation via FFT
    n = len(frame)
    x = frame - frame.mean()
    size = 1 << (2 * n - 1).bit_length()
    X = np.fft.rfft(x, size)
    ac = np.fft.irfft(X * np.conj(X), size)[:n]
    if ac[0] <= 1e-9:
        return 0.0, 0.0
    ac /= ac[0]
    lo = int(SR / FMAX)          # ~20
    hi = min(int(SR / FMIN), n - 1)  # ~147
    seg = ac[lo:hi]
    k = int(np.argmax(seg)) + lo
    # parabolic interpolation around k
    if 0 < k < n - 1:
        a, b, c = ac[k-1], ac[k], ac[k+1]
        denom = a - 2*b + c
        shift = 0.5 * (a - c) / denom if denom != 0 else 0.0
        lag = k + shift
    else:
        lag = float(k)
    freq = SR / lag
    clarity = ac[k]
    return freq, clarity

def main():
    data = read_wav(sys.argv[1] if len(sys.argv) > 1 else 'tools/song.wav')
    nfr = (len(data) - WIN) // HOP
    rms = np.zeros(nfr)
    midi = np.zeros(nfr)
    clar = np.zeros(nfr)
    for i in range(nfr):
        fr = data[i*HOP : i*HOP + WIN]
        rms[i] = np.sqrt((fr**2).mean())
        f, c = autocorr_pitch(fr)
        clar[i] = c
        midi[i] = 69 + 12*np.log2(f/440) if f > 0 else 0

    thr = 0.10 * np.percentile(rms, 95)
    voiced = (rms > thr) & (clar > 0.55) & (midi > 20)
    # mode filter on midi within voiced runs
    mf = midi.copy()
    for i in range(nfr):
        s, e = max(0, i-2), min(nfr, i+3)
        seg = midi[s:e][voiced[s:e]]
        if len(seg):
            mf[i] = np.median(seg)

    def snap(m):
        return int(round(m))

    notes = []
    i = 0
    while i < nfr:
        if voiced[i]:
            j = i
            lastm = snap(mf[i])
            while j < nfr and voiced[j] and abs(snap(mf[j]) - lastm) <= 0 and j - i < 200:
                j += 1
            dur_ms = (j - i) * HOP * 1000 / SR
            m = lastm
            notes.append([m, dur_ms])
            i = j
        else:
            j = i
            while j < nfr and not voiced[j]:
                j += 1
            gap_ms = (j - i) * HOP * 1000 / SR
            if gap_ms >= 90 and notes:
                notes.append([0, gap_ms])   # rest
            i = j

    # merge consecutive same-pitch notes split by tiny gaps, drop too-short notes
    merged = []
    for m, d in notes:
        if d < 90 and m != 0:
            continue
        if merged and merged[-1][0] == m and m != 0 and d < 140 and merged[-1][1] < 400:
            merged[-1][1] += d
        else:
            merged.append([m, d])

    def hz(m):
        return 440.0 * 2 ** ((m - 69) / 12)

    out = []
    for m, d in merged:
        out.append({'f': round(hz(m), 1) if m else 0, 'd': int(round(d / 25) * 25), 'm': m})

    with open('tools/melody.json', 'w', encoding='utf-8') as fp:
        json.dump(out, fp)

    pitches = [o['m'] for o in out if o['m']]
    total_ms = sum(o['d'] for o in out)
    print('notes:', len(out), 'pitched:', len(pitches), 'duration: %.1fs' % (total_ms/1000))
    if pitches:
        print('midi range:', min(pitches), '-', max(pitches))
        uniq, cnt = np.unique(pitches, return_counts=True)
        print('top pitches:', sorted(zip(cnt, uniq), reverse=True)[:8])
    print('first 24:', out[:24])

if __name__ == '__main__':
    main()
