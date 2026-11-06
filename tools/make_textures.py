# Build mod textures from vanilla jar textures (read-only access to the user's instance).
# Also prints vanilla JSON formats (blockstate / item model / recipe / loot table) for reference.
import zipfile, io, os, colorsys
from PIL import Image

JAR = r'D:\MC\.minecraft\versions\1.21.8WithSTM\1.21.8WithSTM.jar'
RES = 'with_stm32/src/main/resources/assets/with_stm32'
os.makedirs(RES + '/textures/block', exist_ok=True)
os.makedirs(RES + '/textures/item', exist_ok=True)

z = zipfile.ZipFile(JAR)

def tex(path):
    return Image.open(io.BytesIO(z.read(path))).convert('RGBA')

def show(path):
    try:
        print('==== ' + path + ' ====')
        print(z.read(path).decode('utf-8'))
    except KeyError:
        print('==== ' + path + ' MISSING ====')

for p in ['assets/minecraft/blockstates/redstone_lamp.json',
          'assets/minecraft/items/redstone_lamp.json',
          'assets/minecraft/models/block/redstone_lamp.json',
          'data/minecraft/recipe/redstone_lamp.json',
          'data/minecraft/loot_table/blocks/redstone_lamp.json']:
    show(p)

def hue_replace(img, target_h, sat_mult=1.15, val_shift=0.0):
    px = img.load()
    out = img.copy()
    po = out.load()
    for y in range(img.height):
        for x in range(img.width):
            r, g, b, a = px[x, y]
            if a == 0: continue
            h, s, v = colorsys.rgb_to_hsv(r/255, g/255, b/255)
            v = min(1.0, max(0.0, v + val_shift))
            nr, ng, nb = colorsys.hsv_to_rgb(target_h, min(1.0, s*sat_mult), v)
            po[x, y] = (int(nr*255), int(ng*255), int(nb*255), a)
    return out

# ---- link lamps from redstone lamp ----
lamp_off = tex('assets/minecraft/textures/block/redstone_lamp.png')
lamp_on  = tex('assets/minecraft/textures/block/redstone_lamp_on.png')
for name, h in [('red', 0.0), ('green', 0.34), ('blue', 0.60)]:
    hue_replace(lamp_off, h).save(f'{RES}/textures/block/link_lamp_{name}_off.png')
    hue_replace(lamp_on, h, val_shift=0.06).save(f'{RES}/textures/block/link_lamp_{name}_on.png')
print('lamps done')

# ---- remote receiver: note block base + antenna glyph ----
base = tex('assets/minecraft/textures/block/note_block.png')

def receiver(state):  # state 0 off, 1 on
    img = base.copy()
    px = img.load()
    # antenna mast rows 2..7 cols 7..8
    mast = (120, 120, 130, 255) if state else (70, 70, 80, 255)
    for y in range(2, 8):
        px[7, y] = mast; px[8, y] = mast
    # tip dot rows 8..11 cols 5..10 (rounded-ish)
    dot_c = (255, 60, 60, 255) if state else (110, 25, 25, 255)
    dot_in = (255, 220, 220, 255) if state else (70, 20, 20, 255)
    rect = [(6, 8), (7, 8), (8, 8), (9, 8),
            (6, 9), (7, 9), (8, 9), (9, 9),
            (7, 10), (8, 10)]
    for x, y in rect:
        px[x, y] = dot_c
    px[7, 9] = dot_in; px[8, 9] = dot_in
    if state:
        # signal arcs
        for x, y in [(4, 3), (5, 2), (10, 2), (11, 3), (3, 5), (12, 5)]:
            px[x, y] = (255, 150, 150, 255)
    return img

receiver(0).save(f'{RES}/textures/block/remote_receiver_off.png')
receiver(1).save(f'{RES}/textures/block/remote_receiver_on.png')
print('receiver done')

# ---- remote transmitter: note block base + antenna + amber LED ----
def transmitter(state):  # state 0 off, 1 on
    img = base.copy()
    px = img.load()
    # antenna mast rows 2..7 cols 7..8
    mast = (140, 140, 150, 255) if state else (70, 70, 80, 255)
    for y in range(2, 8):
        px[7, y] = mast; px[8, y] = mast
    # amber LED block rows 8..11 cols 5..10
    led_c = (255, 170, 40, 255) if state else (120, 80, 20, 255)
    led_in = (255, 230, 180, 255) if state else (70, 50, 15, 255)
    for y in range(8, 12):
        for x in range(5, 11):
            px[x, y] = led_c
    for y in range(9, 11):
        for x in range(7, 9):
            px[x, y] = led_in
    if state:
        # outward signal waves (left and right of the LED)
        for x, y in [(3, 8), (2, 9), (2, 10), (3, 11),
                     (12, 8), (13, 9), (13, 10), (12, 11)]:
            px[x, y] = (255, 200, 90, 255)
    return img

transmitter(0).save(f'{RES}/textures/block/remote_transmitter_off.png')
transmitter(1).save(f'{RES}/textures/block/remote_transmitter_on.png')
print('transmitter done')

# ---- tune whistle from goat horn ----
try:
    horn = tex('assets/minecraft/textures/item/goat_horn.png')
    wh = hue_replace(horn, 0.5, sat_mult=1.2, val_shift=0.05)
    px = wh.load()
    # finger holes
    for x, y in [(4, 7), (7, 5), (10, 4)]:
        px[x, y] = (30, 60, 70, 255)
    wh.save(f'{RES}/textures/item/tune_whistle.png')
    print('whistle done (goat horn base)')
except KeyError:
    print('goat horn missing, drawing whistle from scratch')
    img = Image.new('RGBA', (16, 16), (0, 0, 0, 0))
    px = img.load()
    for x in range(3, 12):
        for y in range(6, 10):
            px[x, y] = (60, 160, 170, 255)
    for y in range(4, 12):
        px[11, y] = (50, 130, 140, 255)
    for x, y in [(5, 7), (8, 7)]:
        px[x, y] = (30, 60, 70, 255)
    img.save(f'{RES}/textures/item/tune_whistle.png')

# ---- mod icon: red lamp on + border, scaled to 128 ----
icon = Image.open(f'{RES}/textures/block/link_lamp_red_on.png')
icon = icon.resize((128, 128), Image.NEAREST)
d = icon.load()
for i in range(128):
    for j in (0, 1, 126, 127):
        d[i, j] = (40, 40, 48, 255)
        d[j, i] = (40, 40, 48, 255)
icon.save('with_stm32/src/main/resources/icon.png')
print('icon done')
