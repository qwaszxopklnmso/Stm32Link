# Arrange a (possibly single-track polyphonic) MIDI into 4 buzzer voices.
#   V1 melody (highest at onset), V2 harmony (2nd), V3 filler (middle ranks),
#   V4 bass (lowest, software square via TIM4 ISR, <= ~260Hz).
# Outputs: tools/preview_mid.wav, Stm32Link_Keil/Hardware/Song.c (+Song.h),
#          with_stm32/.../Stm32Melody.java, tools/melody.json
import struct, wave, io, json, bisect
import numpy as np

SRC = 'SummerExpress.mid'
SR = 22050
MAX_SONG_MS = 200000          # full song fits in flash (~18KB); hard safety cap
MAX_ENTRIES = 12000           # flash budget: entries x 4 bytes < ~48KB

data = open(SRC, 'rb').read()

# ---------------- MIDI parse ----------------
pos = 0
def rd(n):
    global pos
    b = data[pos:pos+n]; pos += n
    return b

assert rd(4) == b'MThd'
hlen, = struct.unpack('>I', rd(4))
fmt, ntrk, div = struct.unpack('>HHH', rd(6))
assert not div & 0x8000, 'SMPTE timing not supported'
TPQ = div

notes = []          # (start_tick, end_tick, pitch, vel)
tempos = []         # (tick, us_per_quarter)
pedals = {}         # channel -> (state, deferred note indices)
active = {}         # (ch,pitch) -> list of note indices

for trk in range(ntrk):
    assert rd(4) == b'MTrk'
    tlen, = struct.unpack('>I', rd(4))
    end = pos + tlen
    tick = 0
    running = 0
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
        ch = st & 0x0F
        if st == 0xFF:
            mt = data[pos]; pos += 1
            ln = 0
            while True:
                b = data[pos]; pos += 1
                ln = (ln << 7) | (b & 0x7F)
                if not b & 0x80: break
            payload = data[pos:pos+ln]; pos += ln
            if mt == 0x51:
                t, = struct.unpack('>I', b'\x00' + payload)
                tempos.append((tick, t))
            elif mt == 0x2F:
                pos = end
        elif hi in (0x80, 0x90, 0xA0, 0xB0, 0xE0):
            d1 = data[pos]; d2 = data[pos+1]; pos += 2
            if hi == 0x90 and d2 > 0:
                idx = len(notes)
                notes.append([tick, None, d1, d2])
                active.setdefault((ch, d1), []).append(idx)
            elif hi == 0x80 or (hi == 0x90 and d2 == 0):
                lst = active.get((ch, d1))
                if lst:
                    i = lst.pop(0)
                    notes[i][1] = tick
            elif hi == 0xB0 and d1 == 64:      # sustain pedal
                if d2 >= 64:
                    pedals[ch] = True
                else:
                    pedals[ch] = False
                    for i in notes:
                        if i[1] is None:
                            i[1] = tick
            elif hi == 0xB0 and d1 == 123:     # all notes off
                for i in notes:
                    if i[1] is None: i[1] = tick
                active.clear()
        elif hi in (0xC0, 0xD0):
            pos += 1
        else:
            pos += 1

for i in notes:
    if i[1] is None:
        i[1] = tick
notes = [n for n in notes if n[1] > n[0]]
print('parsed: %d notes, %d tempo events, TPQ=%d' % (len(notes), len(tempos), TPQ))

# ---------------- ticks -> ms ----------------
tempos.sort()
if not tempos or tempos[0][0] > 0:
    tempos.insert(0, (0, 500000))

def tick_to_ms(t):
    ms = 0.0
    last_tick, last_us = 0, tempos[0][1]
    for tk, us in tempos:
        if tk >= t: break
        ms += (tk - last_tick) * last_us / TPQ / 1000.0
        last_tick, last_us = tk, us
    return ms + (t - last_tick) * last_us / TPQ / 1000.0

end_tick = max(n[1] for n in notes)
total_ms = tick_to_ms(end_tick)
print('song length: %.1fs' % (total_ms / 1000))

# ---------------- voice assignment by chord rank ----------------
# active-set sweep; rank = how many higher pitches are sounding at onset
events = []
for i, (s, e, p, v) in enumerate(notes):
    events.append((s, 1, p, i))
    events.append((e, 0, p, i))
events.sort(key=lambda x: (x[0], x[1]))     # note-offs before note-ons at same tick

active_pitches = []       # sorted (pitch, note_idx)
removed = set()
voice_of = [None] * len(notes)

for t, kind, p, i in events:
    if kind == 0:
        removed.add(i)
        continue
    # rank among currently sounding notes (excluding removed)
    higher = 0
    total = 0
    for k in range(len(active_pitches) - 1, -1, -1):
        if active_pitches[k][1] in removed:
            continue
        total += 1
        if active_pitches[k][0] > p:
            higher += 1
    if total == 0:
        voice_of[i] = 0                    # solo passage -> melody
    elif higher == 0:
        voice_of[i] = 0                    # highest -> melody
    elif higher == 1:
        voice_of[i] = 1                    # 2nd -> harmony
    elif p < min(active_pitches[k][0] for k in range(len(active_pitches)) if active_pitches[k][1] not in removed):
        voice_of[i] = 3                    # strictly lowest -> bass
    else:
        voice_of[i] = 2                    # middle -> filler
    bisect.insort(active_pitches, (p, i))

# ---------------- per-voice monophonize + octave fold ----------------
BANDS = {0: (60, 88), 1: (55, 81), 2: (48, 74), 3: (36, 58)}
def fold(p, lo, hi):
    while p > hi: p -= 12
    while p < lo: p += 12
    return p

voices = [[], [], [], []]
for i, (s, e, p, v) in enumerate(notes):
    vs = voice_of[i]
    lo, hi = BANDS[vs]
    voices[vs].append((tick_to_ms(s), max(50, tick_to_ms(e) - tick_to_ms(s)), fold(p, lo, hi)))

def monophonize(lst):
    lst.sort()
    out = []
    for s, d, p in lst:
        if out and s < out[-1][0] + out[-1][1]:
            out[-1] = (out[-1][0], s - out[-1][0], out[-1][2])   # clip previous
            if out[-1][1] < 40:
                out.pop()
        out.append((s, d, p))
    return out

voices = [monophonize(v) for v in voices]
for vi, v in enumerate(voices):
    print('V%d: %d notes, %.1fs span' % (vi + 1, len(v), (v[-1][0] + v[-1][1] - v[0][0]) / 1000 if v else 0))

# ---------------- window & budget ----------------
start_ms = 0
if total_ms > MAX_SONG_MS:
    # choose 90s window with most note onsets
    best = (0, 0)
    for s in range(0, int(total_ms) - 90000, 15000):
        cnt = sum(1 for v in voices for (t, d, p) in v if s <= t < s + 90000)
        if cnt > best[0]:
            best = (cnt, s)
    start_ms = best[1]
    print('window: %.0fs..%.0fs' % (start_ms / 1000, start_ms / 1000 + 90))
else:
    print('full song kept (%.1fs)' % (total_ms / 1000))

def cut(lst):
    return [(t - start_ms, d, p) for (t, d, p) in lst if start_ms <= t < start_ms + (MAX_SONG_MS if total_ms <= MAX_SONG_MS else 90000)]

voices = [cut(v) for v in voices]

# thin if over budget: drop shortest notes from V2/V3, then longer ones
def total_entries():
    n = 0
    for v in voices:
        cur = 0
        for (t, d, p) in v:
            n += 1 + (1 if t - cur >= 75 else 0)
            cur = t + d
    return n

thr = [0, 60, 60, 60]
while total_entries() > MAX_ENTRIES and thr[1] < 200:
    for vi in (2, 1, 3):
        voices[vi] = [x for x in voices[vi] if x[1] >= thr[vi]]
    thr = [thr[0], thr[1] + 20, thr[2] + 20, thr[3] + 20]
print('entry budget: %d (thr=%s)' % (total_entries(), thr))

# ---------------- sequential encode per voice ----------------
def encode(lst):
    seq = []
    cur = 0
    for (t, d, p) in lst:
        gap = int(round((t - cur) / 25) * 25)
        if gap >= 75:
            seq.append((0, gap))
        dur = int(round(d / 25) * 25)
        freq = round(440.0 * 2 ** ((p - 69) / 12))
        seq.append((freq, max(50, dur)))
        cur = t + d
    while seq and seq[-1][0] == 0:
        seq.pop()
    return seq

seqs = [encode(v) for v in voices]
for vi, s in enumerate(seqs):
    print('V%d: %d entries, %.1fs' % (vi + 1, len(s), sum(x[1] for x in s) / 1000))

# ---------------- preview wav ----------------
total = max(sum(x[1] for x in s) for s in seqs)
buf = np.zeros(int(total / 1000 * SR) + SR // 4)
GAINS = [0.20, 0.16, 0.14, 0.20]
for vi, s in enumerate(seqs):
    pos = 0
    for freq, ms in s:
        n = int(ms / 1000 * SR)
        if freq:
            tt = np.arange(n) / SR
            env = np.minimum(tt / 0.004, 1) * np.exp(-1.6 * tt / max(ms / 1000, 0.05))
            if vi == 3:
                sig = np.sin(2 * np.pi * freq * tt)          # bass smoother
            else:
                sig = np.sign(np.sin(2 * np.pi * freq * tt)) + 0.3 * np.sin(4 * np.pi * freq * tt)
            buf[pos:pos + n] += GAINS[vi] * sig * env
        pos += n
peak = np.abs(buf).max()
if peak > 0:
    buf = buf / peak * 0.85
with wave.open('tools/preview_mid.wav', 'wb') as w:
    w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR)
    w.writeframes((buf * 32767).astype(np.int16).tobytes())
print('preview written (%.1fs)' % (total / 1000))

# ---------------- Song.c ----------------
names = ['V1_Melody', 'V2_Harmony', 'V3_Filler', 'V4_Bass']
decls, defs = [], []
for vi, s in enumerate(seqs):
    rows = ',\n'.join('    {%d, %d}' % (f, m) for f, m in s)
    defs.append('const uint16_t %s[][2] = {\n%s\n};\nconst uint16_t %s_Len = sizeof(%s) / sizeof(%s[0]);'
                % (names[vi], rows, names[vi], names[vi], names[vi]))
song_c = '''#include "Song.h"

// Auto-generated by tools/midi_arrange.py from SummerExpress.mid - do not edit.
// Each entry: {frequency in Hz (0 = rest), duration in ms}.
%s

''' % '\n\n'.join(defs)
io.open('Stm32Link_Keil/Hardware/Song.c', 'w', encoding='ascii').write(song_c)

song_h = '''#ifndef __SONG_H
#define __SONG_H

#include "stm32f10x.h"

// Auto-generated by tools/midi_arrange.py from SummerExpress.mid - do not edit.
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
'''
io.open('Stm32Link_Keil/Hardware/Song.h', 'w', encoding='ascii').write(song_h)

# ---------------- Stm32Melody.java ----------------
def jnum(x):
    return ('%d.0f' % x) if x else '0.0f'
blocks = []
for vi, s in enumerate(seqs):
    rows = ',\n'.join('            {%s, %d}' % (jnum(f), m) for f, m in s)
    blocks.append('        {\n%s\n        }' % rows)
java = '''package qw.with_stm32;

// Auto-generated by tools/midi_arrange.py from SummerExpress.mid - do not edit.
// VOICES[0..3] = {melody, harmony, filler, bass}; each note {frequency Hz (0=rest), duration ms}.
public final class Stm32Melody {
    public static final int NUM_VOICES = 4;
    public static final float[][][] VOICES = {
%s
    };

    private Stm32Melody() {}
}
''' % ',\n'.join(blocks)
io.open('with_stm32/src/main/java/qw/with_stm32/Stm32Melody.java', 'w', encoding='ascii').write(java)
print('Song.c/h + Stm32Melody.java written')
