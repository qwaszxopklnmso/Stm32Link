from PIL import Image, ImageDraw, ImageFont

W, H = 1800, 1200
img = Image.new("RGB", (W, H), "#f4f6fa")
d = ImageDraw.Draw(img)

FONT = "C:/Windows/Fonts/msyh.ttc"
FONTB = "C:/Windows/Fonts/msyhbd.ttc"


def F(sz, bold=False):
    return ImageFont.truetype(FONTB if bold else FONT, sz)


def T(x, y, s, sz=22, fill="#111820", bold=False, anchor="la", stroke=0, sfill="#ffffff"):
    d.text((x, y), s, font=F(sz, bold), fill=fill, anchor=anchor,
           stroke_width=stroke, stroke_fill=sfill)


def L(pts, fill, width=6):
    d.line(pts, fill=fill, width=width, joint="curve")


def dot(x, y, r=4, fill="#cfd6df"):
    d.ellipse((x - r, y - r, x + r, y + r), fill=fill)


def num(x, y, n):
    d.ellipse((x - 11, y - 11, x + 11, y + 11), fill="#1565c0", outline="#ffffff", width=2)
    T(x, y, str(n), 13, "#ffffff", True, "mm")


# ---------------- title ----------------
T(55, 30, "蜂鸣器接线 · 先接这一组（V1 电磁 + V4 压电）", 38, "#0f2742", True)
T(55, 84, "按编号 1–16 和 E/B/C 标注接线；V2/V3 要四声部时照抄这一组", 23, "#4a5a70")

# ---------------- 5V module ----------------
d.rounded_rectangle((120, 145, 420, 335), radius=14, fill="#1565c0", outline="#0b3d75", width=4)
T(270, 158, "5V 2A 电源", 22, "#ffffff", True, "ma")
d.rectangle((140, 195, 195, 300), fill="#263238", outline="#111", width=2)
T(130, 310, "7–10V 模块 / 5V 充电头", 9, "#ffffff", anchor="la")
d.rectangle((330, 205, 400, 260), fill="#cfd8dc", outline="#8b939e", width=2)
T(365, 272, "5V OUT", 14, "#ffffff", anchor="ma")
# 5V and GND out
L([(420, 210), (450, 210), (450, 380), (1700, 380)], "#e53935", 6)
L([(420, 290), (1720, 290), (1720, 900), (1700, 900)], "#111820", 6)
T(445, 190, "5V", 15, "#e53935", True, "ra", 2)
T(445, 305, "GND", 15, "#111820", True, "ra", 2)

# ---------------- 5V / GND rails ----------------
L([(80, 380), (1700, 380)], "#e53935", 6)
L([(80, 900), (1700, 900)], "#111820", 6)
T(80, 355, "+5V 轨", 17, "#e53935", True, "la")
T(80, 915, "GND 轨", 17, "#111820", True, "la")
for x in range(95, 1695, 24):
    dot(x, 380, 3, "#f0b6b6")
    dot(x, 900, 3, "#b8bec7")

# ---------------- STM32 ----------------
d.rounded_rectangle((100, 470, 360, 880), radius=14, fill="#17365d", outline="#0b2038", width=4)
d.rectangle((190, 450, 270, 474), fill="#c3c9d2", outline="#8b939e", width=2)
T(230, 462, "USB", 12, "#333", anchor="mm")
T(230, 500, "STM32F103C8T6", 17, "#ffffff", True, "ma")
T(230, 528, "USB / ST-Link 供电", 12, "#b9cbe4", anchor="ma")
T(230, 560, "只用 GND 共地", 14, "#ffcc80", anchor="ma")

# pins on right edge
pins = [("PA0 / V1", 520, "#f9a825"), ("PA5 / V4", 590, "#1e88e5"),
        ("GND", 700, "#111820"), ("PA8 / V2", 770, "#8a97a8"),
        ("PA6 / V3", 830, "#8a97a8")]
for name, y, col in pins:
    d.rectangle((352, y - 5, 368, y + 5), fill="#d4af37")
    T(374, y, name, 16, "#ffffff" if col != "#8a97a8" else "#aeb8c6", anchor="la")


# ---------------- breadboard ----------------
d.rounded_rectangle((420, 470, 1180, 870), radius=16, fill="#fdfdfd", outline="#c6ced9", width=3)
T(440, 478, "面包板（这一组）", 15, "#7a8798")
x0, y0, dx, dy = 455, 515, 36, 40
for r in range(8):
    for c in range(20):
        dot(x0 + c * dx, y0 + r * dy, 3, "#d5dbe3")

# ---------------- V1: PA0 -> 330R -> B ----------------
L([(368, 520), (540, 520)], "#f9a825", 6)
# 330 resistor
d.rounded_rectangle((540, 505, 625, 537), radius=11, fill="#e8d5b0", outline="#8d6e4a", width=2)
for bx, bc in [(558, "#ef6c00"), (570, "#ef6c00"), (582, "#6d4c41"), (594, "#d4af37")]:
    d.rectangle((bx, 507, bx + 5, 535), fill=bc)
T(582, 488, "330Ω", 16, "#6d4c41", True, "ma")
L([(625, 520), (685, 520), (685, 740), (755, 740)], "#f9a825", 6)

# S8050
d.pieslice((718, 590, 792, 664), 180, 360, fill="#1b1b1b", outline="#000000", width=3)
for x, lab in [(738, "E"), (755, "B"), (772, "C")]:
    L([(x, 635), (x, 740)], "#b0b7c0", 6)
    T(x, 748, lab, 15, "#ffffff", True, "ma", 2)
T(755, 570, "S8050", 18, "#ffffff", True, "ma", 2)

# E -> GND
L([(738, 740), (738, 900)], "#111820", 6)
# B node to 10k
L([(755, 740), (755, 755), (710, 755), (710, 770)], "#6a1b9a", 5)
# 10k (left of the transistor, below the 330R)
d.rounded_rectangle((660, 770, 694, 850), radius=10, fill="#e8d5b0", outline="#8d6e4a", width=2)
for by, bc in [(780, "#6d4c41"), (790, "#111820"), (800, "#ef6c00")]:
    d.rectangle((662, by, 692, by + 5), fill=bc)
T(700, 815, "10k", 16, "#6d4c41", True, "la")
L([(677, 850), (677, 900)], "#111820", 6)

# C -> EM -
L([(772, 740), (772, 780), (980, 780), (980, 565)], "#2e7d32", 6)

# ---------------- EM ----------------
d.ellipse((930, 475, 1030, 575), fill="#20242a", outline="#0b0d10", width=4)
d.ellipse((960, 505, 1000, 545), fill="#3a4048")
d.ellipse((972, 517, 988, 533), fill="#0b0d10")
T(980, 458, "+", 24, "#e53935", True, "ma")
T(980, 590, "−", 24, "#111820", True, "ma")
T(980, 612, "EM 16Ω 2kHz", 15, "#334155", True, "ma")
L([(980, 475), (980, 380)], "#e53935", 6)

# flyback diode
d.rounded_rectangle((1050, 548, 1080, 652), radius=6, fill="#1b1b1b", outline="#000", width=2)
d.rectangle((1050, 548, 1080, 560), fill="#c9ced6")
T(1090, 540, "K", 15, "#111820", True, "la")
T(1090, 640, "A", 15, "#111820", True, "la")
T(1065, 670, "1N4007", 14, "#334155", True, "ma")
L([(1065, 548), (1065, 380)], "#e53935", 5)
L([(1065, 652), (1065, 760), (980, 760)], "#ef6c00", 5)
T(1095, 585, "反并", 13, "#ef6c00", True, "la", 2)

# ---------------- V4 piezo ----------------
d.rounded_rectangle((1350, 600, 1650, 740), radius=12, fill="#0d47a1", outline="#062b63", width=3)
d.ellipse((1375, 635, 1445, 705), fill="#20242a", outline="#0b0d10", width=3)
d.ellipse((1398, 658, 1422, 682), fill="#3a4048")
T(1410, 718, "MH-FMD", 13, "#ffffff", anchor="ma")
T(1520, 615, "压电模块 5V", 17, "#ffffff", True, "ma")
T(1460, 645, "VCC", 14, "#ffffff", anchor="la")
T(1460, 675, "GND", 14, "#ffffff", anchor="la")
T(1460, 705, "I/O", 14, "#ffffff", anchor="la")
for y in [650, 680, 710]:
    d.rectangle((1438, y - 4, 1452, y + 4), fill="#d4af37")
L([(1452, 650), (1300, 650), (1300, 380)], "#e53935", 5)
L([(1452, 680), (1280, 680), (1280, 900)], "#111820", 6)
# PA5 -> IO
L([(368, 590), (450, 590)], "#1e88e5", 6)
T(410, 605, "PA5 → 压电 I/O", 15, "#0d47a1", True, "la", 2)
L([(1438, 710), (1375, 710)], "#1e88e5", 6)
T(1360, 725, "← PA5", 14, "#0d47a1", True, "ra", 2)

# ---------------- STM32 GND ----------------
L([(368, 700), (390, 700), (390, 900)], "#111820", 6)

# ---------------- numbers ----------------
num(430, 210, 1)
num(430, 290, 2)
num(380, 700, 3)
num(380, 520, 4)
num(650, 520, 5)

num(980, 490, 8)
num(1075, 548, 9)
num(1075, 652, 10)
num(690, 865, 11)
num(380, 590, 12)
num(1320, 650, 13)
num(1320, 680, 14)
num(1320, 710, 15)


# ---------------- notes ----------------
notes = [
    "① V1 默认高触发（NPN）；若被设成低触发，发 Y1:0 或把 BUZZ_TRIG_LOW_V1 改成 0；V4 低触发默认。",
    "② S8050 平面朝自己 E-B-C；1N4007 色环端 K 接 5V，A 接 C。",
    "③ 5V 2A 电源（模块/充电头）；STM32 只用 GND 共地，5V 不要并接。",
    "④ V2/V3 要接：PA8/PA6 各复制一组（330Ω→B，E→GND，C→EM−，EM+→5V，1N4007 反并）。",
    "⑤ 5V 轨并 100–470µF 更好；3V 也能响但小声，5V 推荐。",
    "⑥ E→GND，C→EM−，B→10k（见图中 E/B/C 标注）。",
    "⑦ 半圆 = S8050 三极管；黑圆 = EM 电磁；蓝块 = 压电模块。",
]
for i, s in enumerate(notes):
    # simple text with white halo, placed in a light panel
    pass

d.rounded_rectangle((55, 940, 1745, 1145), radius=12, fill="#fffdf5", outline="#e6d3a3", width=2)
for i, s in enumerate(notes):
    T(75, 950 + i * 28, s, 16, "#5b4300")

T(55, 1165, "先接 V1 一组，能响再加 V2/V3；孔位可左右平移，按编号连接即可。", 15, "#7a8798")

img.save("buzzer_wiring.png")
print("saved", img.size)
