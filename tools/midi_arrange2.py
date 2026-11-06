# Arrange SummerExpress.mid (BLACK MIDI: ~79 notes sounding at once, median dur 47ms)
# into 4 buzzer voices via slice-sampling reduction:
#   every 80ms slice -> highest pitch = V1 melody, 2nd highest = V2 harmony,
#   lowest = V4 bass, 3rd highest = V3 filler; everything else discarded.
# Consecutive slices within +-1 semitone merge into one note; min note 2 slices.
import struct, wave, io
import numpy as np

SRC = 'SummerExpress.mid'
SR = 22050
SLICE = 80.0        # ms per sample slice

data = open(SRC, 'rb').read()

# ---------------- MIDI parse (format 0, single track) ----------------
assert data[0:4] == b'MThd'
hlen, = struct.unpack('>I', data[4:8])
fmt, ntrk, div = struct.unpack('>HHH', data[8:14])
pos = 8 + hlen
assert data[pos:pos+4] == b'MTrk'; pos += 4
tlen, = struct.unpack('>I', data[pos:pos+4]); pos += 4
end = pos + tlen
tick = 0; running = 0
events = []
while pos < end:
    delta = 0
    while True:
        b = data[pos]; pos += 1
        delta = (delta << 7) | (b & 0x7F)
        if not b & 0x80: break
    tick += delta
    st = data[pos]
    if st & 0x80: pos += 1
    else: st = running
    running = st
    hi = st & 0xF0
    if st == 0xFF:
        mt = data[pos]; pos += 1
        ln = 0
        while True:
            b = data[pos]; pos += 1
            ln = (ln << 7) | (b & 0x7F)
            if not b & 0x80: break
        pos += ln
    elif hi in (0x80, 0x90, 0xA0, 0xB0, 0xE0):
        d1 = data[pos]; d2 = data[pos+1]; pos += 2
        if hi == 0x90 and d2 > 0: events.append((tick, 1, d1))
        elif hi == 0x80 or (hi == 0x90 and d2 == 0): events.append((tick, 0, d1))
    elif hi in (0xC0, 0xD0): pos += 1
    else: pos += 1

import collections
act = collections.defaultdict(list)
parsed = []
for t, k, p in events:
    if k == 1: act[p].append(t)
    else:
        if act[p]: parsed.append((act[p].pop(0), t, p))
parsed.sort()
TPQ = div if not div & 0x8000 else 480
ms_per_tick = 500.0 / TPQ          # tempo 500000us/quarter
total_ms = tick * ms_per_tick
print('notes: %d, song %.1fs' % (len(parsed), total_ms / 1000))

# ---------------- slice sampling ----------------
nslices = int(total_ms / SLICE)
sounding = [[] for _ in range(nslices)]
for (s, e, p) in parsed:
    a = int(s * ms_per_tick / SLICE)
    b = min(nslices - 1, int(e * ms_per_tick / SLICE))
    for k in range(a, b + 1):
        sounding[k].append(p)

def fold(p, lo, hi):
    while p > hi: p -= 12
    while p < lo: p += 12
    return p

BANDS = {0: (62, 86), 1: (57, 81), 2: (52, 76), 3: (38, 58)}

def trackize(arr, min_slices=2):
    """arr: list of raw midi pitch or None per slice -> note list (start_slice, end_slice, pitch)"""
    notes = []
    cur = None
    for k, p in enumerate(arr):
        if p is None:
            if cur is not None:
                if k - cur[0] >= min_slices: notes.append((cur[0], k, cur[2]))
                cur = None
            continue
        if cur is not None and abs(p - cur[2]) <= 1:
            cur = (cur[0], k, p)          # extend, allow slight drift
        else:
            if cur is not None and k - cur[0] >= min_slices:
                notes.append((cur[0], k, cur[2]))
            cur = (k, k, p)
    if cur is not None and len(arr) - cur[0] >= min_slices:
        notes.append((cur[0], len(arr), cur[2]))
    return notes

cols = {0: [], 1: [], 2: [], 3: []}
for k in range(nslices):
    ps = sorted(set(sounding[k]))
    if not ps:
        for vi in cols: cols[vi].append(None)
        continue
    cols[0].append(ps[-1])                       # highest -> melody
    cols[1].append(ps[-2] if len(ps) >= 2 else None)
    cols[2].append(ps[-3] if len(ps) >= 3 else None)
    cols[3].append(ps[0])                        # lowest -> bass

voices = []
for vi in range(4):
    raw = trackize(cols[vi])
    lo, hi = BANDS[vi]
    mono = []
    for (a, b, p) in raw:
        s_ms, e_ms = a * SLICE, b * SLICE
        if mono and s_ms < mono[-1][0] + mono[-1][1]:
            mono[-1] = (mono[-1][0], s_ms - mono[-1][0], mono[-1][2])
        mono.append((s_ms, e_ms - s_ms, fold(p, lo, hi)))
    voices.append([(s, d, p) for (s, d, p) in mono if d >= 100])
    print('V%d: %d notes' % (vi + 1, len(voices[-1])))

# ---------------- sequential encode ----------------
def encode(lst):
    seq = []
    cur = 0
    for (t, d, p) in sorted(lst):
        gap = int(round((t - cur) / 25) * 25)
        if gap >= 100:
            seq.append((0, gap))
        seq.append((round(440.0 * 2 ** ((p - 69) / 12)), max(75, int(round(d / 25) * 25))))
        cur = t + d
    while seq and seq[-1][0] == 0:
        seq.pop()
    return seq

seqs = [encode(v) for v in voices]
for vi, s in enumerate(seqs):
    print('V%d: %d entries, %.1fs' % (vi + 1, len(s), sum(x[1] for x in s) / 1000))

# ---------------- preview wavs (4-voice and melody+bass) ----------------
def synth(active_voices, path):
    total = max(sum(x[1] for x in seqs[vi]) for vi in active_voices)
    buf = np.zeros(int(total / 1000 * SR) + SR // 4)
    GAINS = {0: 0.20, 1: 0.15, 2: 0.13, 3: 0.20}
    for vi in active_voices:
        pos = 0
        for freq, ms in seqs[vi]:
            n = int(ms / 1000 * SR)
            if freq:
                tt = np.arange(n) / SR
                env = np.minimum(tt / 0.004, 1) * np.exp(-1.2 * tt / max(ms / 1000, 0.05))
                if vi == 3:
                    sig = np.sin(2 * np.pi * freq * tt)
                else:
                    sig = np.sign(np.sin(2 * np.pi * freq * tt)) + 0.3 * np.sin(4 * np.pi * freq * tt)
                buf[pos:pos + n] += GAINS[vi] * sig * env
            pos += n
    peak = np.abs(buf).max()
    if peak > 0: buf = buf / peak * 0.85
    with wave.open(path, 'wb') as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR)
        w.writeframes((buf * 32767).astype(np.int16).tobytes())
    print('wrote', path)

synth([0, 1, 2, 3], 'tools/preview_mid.wav')
synth([0, 3], 'tools/preview_mid_2v.wav')

# ---------------- Song.c / Song.h / Stm32Melody.java ----------------
names = ['V1_Melody', 'V2_Harmony', 'V3_Filler', 'V4_Bass']
defs = []
for vi, s in enumerate(seqs):
    rows = ',\n'.join('    {%d, %d}' % (f, m) for f, m in s)
    defs.append('const uint16_t %s[][2] = {\n%s\n};\nconst uint16_t %s_Len = sizeof(%s) / sizeof(%s[0]);'
                % (names[vi], rows, names[vi], names[vi], names[vi]))
io.open('Stm32Link_Keil/Hardware/Song.c', 'w', encoding='ascii').write(
    '''#include "Song.h"

// Auto-generated by tools/midi_arrange2.py from SummerExpress.mid (black-MIDI slice reduction) - do not edit.
// Each entry: {frequency in Hz (0 = rest), duration in ms}.
%s

''' % '\n\n'.join(defs))

io.open('Stm32Link_Keil/Hardware/Song.h', 'w', encoding='ascii').write('''#ifndef __SONG_H
#define __SONG_H

#include "stm32f10x.h"

// Auto-generated by tools/midi_arrange2.py from SummerExpress.mid - do not edit.
extern const uint16_t V1_Melody[][2];
extern const uint16_t V1_Melody_Len;
extern const uint16_t V2_Harmony[][2];
extern const uint16_t V2_Harmony_Len;
extern const uint16_t V3_Filler[][2];
extern const uint16_t V3_Filler_Len;
extern const uint16_t V4_Bass[][2];
extern const uint16_t V4_Bass_Len;

#define SONG_VOICES 4

#endif
''')

def jnum(x):
    return ('%d.0f' % x) if x else '0.0f'
blocks = []
for vi, s in enumerate(seqs):
    rows = ',\n'.join('            {%s, %d}' % (jnum(f), m) for f, m in s)
    blocks.append('        {\n%s\n        }' % rows)
io.open('with_stm32/src/main/java/qw/with_stm32/Stm32Melody.java', 'w', encoding='ascii').write(
    '''package qw.with_stm32;

// Auto-generated by tools/midi_arrange2.py from SummerExpress.mid (black-MIDI slice reduction) - do not edit.
// VOICES[0..3] = {melody, harmony, filler, bass}; each note {frequency Hz (0=rest), duration ms}.
public final class Stm32Melody {
    public static final int NUM_VOICES = 4;
    public static final float[][][] VOICES = {
%s
    };

    private Stm32Melody() {}
}
''' % ',\n'.join(blocks))
print('Song.c/h + Stm32Melody.java written')
