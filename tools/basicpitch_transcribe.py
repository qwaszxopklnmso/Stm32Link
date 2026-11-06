# Transcribe via Basic Pitch, then compress to 4 monophonic buzzer voices with
# MINIMAL intervention (user approved the raw output; arrangement must stay faithful):
#   1. octave-double collapse (F#5+F#6 -> F#5; deep bass keeps higher octave)
#   2. 50ms slices; per slice keep up to 4 notes (lowest + highest + strongest middles)
#   3. persistent nearest-pitch pairing to voices (no cross-voice reassignment)
#   4. equal loudness on all voices (raw MIDI is equal-velocity)
import subprocess, wave, io, struct
import numpy as np

SRC = 'Audio_8bit琵琶曲.m4s'
SR = 22050
BPM = 71.0
FFMPEG = r'E:\ffmpeg-8.1.2-essentials_build\bin\ffmpeg.exe'
AMP_MIN = 0.35
SLICE = 50.0

# ---------- decode + Basic Pitch ----------
subprocess.run([FFMPEG, '-v', 'error', '-y', '-i', SRC, '-ac', '1', '-ar', str(SR),
                'tools/song8.wav'], check=True)
from basic_pitch.inference import predict
model_output, midi_data, note_events = predict('tools/song8.wav')
midi_data.write('tools/pipa_basicpitch_raw.mid')
print('raw MIDI note events: %d' % len(note_events))

notes = [(s * 1000, e * 1000, int(p), float(a)) for (s, e, p, a, *_) in note_events
         if a >= AMP_MIN and e > s]
print('amp>=%.2f: %d notes' % (AMP_MIN, len(notes)))

# ---------- light quantize (snap onsets, keep durations, dedupe exact) ----------
notes.sort(key=lambda x: (x[0], -x[3]))
q = []
for (t, e, p, a) in notes:
    d = e - t
    ts = round(t / 25) * 25
    dq = max(round(d / 25) * 25, 75)
    dup = next((k for k, kk in enumerate(q) if kk[2] == p and abs(kk[0] - ts) < 60), None)
    if dup is not None:
        q[dup][1] = max(q[dup][1], ts + dq)
        continue
    q.append([ts, ts + dq, p, a])
print('quantized: %d' % len(q))

# ---------- octave-double collapse ----------
# Collapse applies only AFTER 19.4s: the intro keeps its octave doubles (user
# request — thickens the sparse front); the drone bridge after it is cut anyway.
DOUBLE_FREE_END = 19.4 * 1000
kept = []
for (t, e, p, a) in q:
    if t >= DOUBLE_FREE_END:
        hit = None
        for k in kept:
            if t < k[1] and e > k[0] and abs(p - k[2]) in (12, 24):
                hit = k; break
        if hit is not None:
            hit[1] = max(hit[1], e)
            hit[3] = max(hit[3], a)
            if min(p, hit[2]) < 55:
                hit[2] = max(p, hit[2])       # deep bass: keep the higher octave
            continue
    kept.append([t, e, p, a])
print('after octave collapse (intro keeps doubles): %d' % len(kept))

# ---------- per-slice rank-by-height (stateless: cannot strand or jitter) ----------
total_ms = max(e for (t, e, p, a) in kept)
nslices = int(total_ms / SLICE) + 1
sounding = [[] for _ in range(nslices)]
for (t, e, p, a) in kept:
    for k in range(int(t / SLICE), min(nslices - 1, int(e / SLICE)) + 1):
        sounding[k].append(p)

runs = [[] for _ in range(4)]      # runs[0] = highest note per slice ... runs[3] = lowest
for k in range(nslices):
    uniq = sorted(set(sounding[k]), reverse=True)   # highest first
    for v in range(4):
        runs[v].append(uniq[v] if v < len(uniq) else None)

# Cut the sparse drone bridge (19.4s-27.0s of the source: long held p69 + fixed
# bass ostinato, user-requested removal). Timelines splice after the cut.
CUT_LO, CUT_HI = int(19.4 * 1000 / SLICE), int(27.0 * 1000 / SLICE)   # SLICE is in ms
for v in range(4):
    runs[v] = runs[v][:CUT_LO] + runs[v][CUT_HI:]

# Buzzer-audible register per voice: a small electromagnetic buzzer cannot make
# fundamentals below ~250Hz audibly (the chiptune's low notes are audible only via
# their square-wave harmonics, which a buzzer does not produce). Fold each voice
# into its singing range so low passages are not silent.
VFOLD = {0: (62, 88), 1: (57, 83), 2: (55, 79), 3: (55, 69)}
def fold(p, lo, hi):
    while p > hi: p -= 12
    while p < lo: p += 12
    return p

voices = []
for v in range(4):
    lo, hi = VFOLD[v]
    r = runs[v]
    out = []
    i = 0
    while i < len(r):
        if r[i] is None:
            i += 1; continue
        j = i
        while j + 1 < len(r) and r[j + 1] is not None and abs(r[j + 1] - fold(r[j], lo, hi)) <= 1:
            j += 1
        d_ms = (j - i + 1) * SLICE
        if d_ms >= 100:
            out.append((i * SLICE, d_ms, fold(r[i], lo, hi)))
        i = j + 1
    voices.append(out)
    ps = [p for (t, d, p) in out]
    iv = np.abs(np.diff(ps)) if len(ps) > 1 else np.array([0])
    print('V%d: %d notes, interval p50=%.0f p90=%.0f, >7sem %.0f%%'
          % (v + 1, len(ps), np.percentile(iv, 50), np.percentile(iv, 90), (iv > 7).mean() * 100))

# ---------- sequential encode ----------
def encode(lst):
    seq = []
    cur = 0
    for (t, d, p) in sorted(lst):
        ts = round(t / 25) * 25
        dq = max(round(d / 25) * 25, 75)
        gap = int(round((ts - cur) / 25) * 25)
        if gap >= 100: seq.append((0, gap))
        seq.append((round(440.0 * 2 ** ((p - 69) / 12)), dq))
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
        evs.append((ms2tick(t), bytes([0x90, int(p), 100])))
        evs.append((ms2tick(t + d), bytes([0x80, int(p), 0])))
    evs.sort(key=lambda x: x[0])
    tracks.append(track_chunk(evs))
midi = (b'MThd' + struct.pack('>IHHH', 6, 1, 5, TPQ)) + b''.join(tracks)
io.open('tools/pipa_8bit.mid', 'wb').write(midi)
print('wrote tools/pipa_8bit.mid (%d bytes)' % len(midi))

# ---------------- preview (equal loudness, like the raw the user approved) ----------------
def synth(path):
    total = max(sum(x[1] for x in s) for s in seqs)
    buf = np.zeros(int(total / 1000 * SR) + SR // 4)
    G = [0.18, 0.18, 0.18, 0.18]
    for vi, s in enumerate(seqs):
        pos = 0
        for freq, ms in s:
            n = int(ms / 1000 * SR)
            if freq:
                tt = np.arange(n) / SR
                env = np.minimum(tt / 0.004, 1) * np.exp(-0.8 * tt / max(ms / 1000, 0.05))
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

// Auto-generated by tools/basicpitch_transcribe.py (8-bit pipa via Basic Pitch, minimal-intervention) - do not edit.
// Each entry: {frequency in Hz (0 = rest), duration in ms}.
%s

''' % '\n\n'.join(defs))
io.open('Stm32Link_Keil/Hardware/Song2.h', 'w', encoding='ascii').write('''#ifndef __SONG2_H
#define __SONG2_H

#include "stm32f10x.h"

// Auto-generated by tools/basicpitch_transcribe.py (8-bit pipa) - do not edit.
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

// Auto-generated by tools/basicpitch_transcribe.py (8-bit pipa via Basic Pitch, minimal-intervention) - do not edit.
// VOICES[0..3]; each note {frequency Hz (0=rest), duration ms}.
public final class Stm32Melody2 {
    public static final int NUM_VOICES = 4;
    public static final float[][][] VOICES = {
%s
    };

    private Stm32Melody2() {}
}
''' % ',\n'.join(blocks))
print('Song2.c/h + Stm32Melody2.java written')
