# Generate all resource JSONs for the mod (blockstates, models, items, lang, loot, recipes, tags)
# and patch fabric.mod.json / mixins config.
import json, io, os

BASE = 'with_stm32/src/main/resources'
NS = 'with_stm32'

def w(path, obj):
    full = os.path.join(BASE, path)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with io.open(full, 'w', encoding='utf-8') as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)

# ---- blockstates ----
for color in ['red', 'green', 'blue']:
    w(f'assets/{NS}/blockstates/link_lamp_{color}.json', {
        'variants': {
            'lit=false': {'model': f'{NS}:block/link_lamp_{color}_off'},
            'lit=true': {'model': f'{NS}:block/link_lamp_{color}_on'},
        }})
for name in ['remote_receiver', 'remote_transmitter']:
    w(f'assets/{NS}/blockstates/{name}.json', {
        'variants': {
            'powered=false': {'model': f'{NS}:block/{name}_off'},
            'powered=true': {'model': f'{NS}:block/{name}_on'},
        }})

# ---- block models ----
for color in ['red', 'green', 'blue']:
    for lit in ['off', 'on']:
        w(f'assets/{NS}/models/block/link_lamp_{color}_{lit}.json', {
            'parent': 'minecraft:block/cube_all',
            'textures': {'all': f'{NS}:block/link_lamp_{color}_{lit}'}})
for name in ['remote_receiver', 'remote_transmitter']:
    for st in ['off', 'on']:
        w(f'assets/{NS}/models/block/{name}_{st}.json', {
            'parent': 'minecraft:block/cube_all',
            'textures': {'all': f'{NS}:block/{name}_{st}'}})

# ---- item models (1.21.4+ items/*.json definitions) ----
for color in ['red', 'green', 'blue']:
    w(f'assets/{NS}/items/link_lamp_{color}.json', {
        'model': {'type': 'minecraft:model', 'model': f'{NS}:block/link_lamp_{color}_off'}})
for name in ['remote_receiver', 'remote_transmitter']:
    w(f'assets/{NS}/items/{name}.json', {
        'model': {'type': 'minecraft:model', 'model': f'{NS}:block/{name}_off'}})
w(f'assets/{NS}/items/tune_whistle.json', {
    'model': {'type': 'minecraft:model', 'model': f'{NS}:item/tune_whistle'}})
w(f'assets/{NS}/models/item/tune_whistle.json', {
    'parent': 'minecraft:item/generated',
    'textures': {'layer0': f'{NS}:item/tune_whistle'}})

# ---- lang ----
w(f'assets/{NS}/lang/en_us.json', {
    'itemGroup.with_stm32': 'STM32 Link',
    f'block.{NS}.link_lamp_red': 'Link Lamp (Red)',
    f'block.{NS}.link_lamp_green': 'Link Lamp (Green)',
    f'block.{NS}.link_lamp_blue': 'Link Lamp (Blue)',
    f'block.{NS}.remote_receiver': 'Telemetry Receiver (STM32→MC)',
    f'block.{NS}.remote_transmitter': 'Telemetry Transmitter (MC→STM32)',
    f'item.{NS}.tune_whistle': 'Tune Whistle',
})
w(f'assets/{NS}/lang/zh_cn.json', {
    'itemGroup.with_stm32': 'STM32 互联',
    f'block.{NS}.link_lamp_red': '联控灯（红）',
    f'block.{NS}.link_lamp_green': '联控灯（绿）',
    f'block.{NS}.link_lamp_blue': '联控灯（蓝）',
    f'block.{NS}.remote_receiver': '遥测接收器（STM32→MC）',
    f'block.{NS}.remote_transmitter': '遥测发射器（MC→STM32）',
    f'item.{NS}.tune_whistle': '曲哨',
})

# ---- loot tables (drop self) ----
blocks = ['link_lamp_red', 'link_lamp_green', 'link_lamp_blue', 'remote_receiver', 'remote_transmitter']
for b in blocks:
    w(f'data/{NS}/loot_table/blocks/{b}.json', {
        'type': 'minecraft:block',
        'pools': [{
            'bonus_rolls': 0.0,
            'conditions': [{'condition': 'minecraft:survives_explosion'}],
            'entries': [{'type': 'minecraft:item', 'name': f'{NS}:{b}'}],
            'rolls': 1.0,
        }],
        'random_sequence': f'{NS}:blocks/{b}',
    })

# ---- recipes ----
def shapeless(ingredients, result, category='redstone'):
    return {'type': 'minecraft:crafting_shapeless', 'category': category,
            'ingredients': ingredients, 'result': {'count': 1, 'id': result}}

def shaped(pattern, key, result, category='redstone'):
    return {'type': 'minecraft:crafting_shaped', 'category': category,
            'key': key, 'pattern': pattern, 'result': {'count': 1, 'id': result}}

dyes = {'red': 'minecraft:red_dye', 'green': 'minecraft:green_dye', 'blue': 'minecraft:blue_dye'}
for color, dye in dyes.items():
    w(f'data/{NS}/recipe/link_lamp_{color}.json',
      shapeless(['minecraft:redstone_lamp', dye], f'{NS}:link_lamp_{color}', 'building'))
w(f'data/{NS}/recipe/remote_receiver.json',
  shaped(['III', 'IRI', ' I '], {'I': 'minecraft:iron_ingot', 'R': 'minecraft:redstone'}, f'{NS}:remote_receiver'))
w(f'data/{NS}/recipe/remote_transmitter.json',
  shaped([' I ', 'IRI', 'III'], {'I': 'minecraft:iron_ingot', 'R': 'minecraft:redstone'}, f'{NS}:remote_transmitter'))
w(f'data/{NS}/recipe/tune_whistle.json',
  shapeless(['minecraft:note_block', 'minecraft:stick'], f'{NS}:tune_whistle', 'misc'))

# ---- tags ----
w('data/minecraft/tags/block/mineable/pickaxe.json', {'values': [f'{NS}:{b}' for b in blocks]})

# ---- fabric.mod.json ----
fmj = json.load(io.open(f'{BASE}/fabric.mod.json', encoding='utf-8'))
fmj['name'] = 'With STM32'
fmj['description'] = 'MC <-> STM32 serial link: link lamps, telemetry receiver/transmitter and a synchronized tune whistle. See STM32_Set.md for wiring.'
fmj['authors'] = ['qw']
json.dump(fmj, io.open(f'{BASE}/fabric.mod.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=2)

# ---- mixins config: main mixin class was removed ----
mix = {'required': True, 'package': 'qw.with_stm32.mixin', 'compatibilityLevel': 'JAVA_21',
       'mixins': [], 'injectors': {'defaultRequire': 1}}
json.dump(mix, io.open(f'{BASE}/{NS}.mixins.json', 'w', encoding='utf-8'), indent=2)

print('resources generated OK')
