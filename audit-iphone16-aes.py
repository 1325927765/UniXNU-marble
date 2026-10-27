#!/usr/bin/env python3
"""Measure the iPhone16 AES vtable against the actually compiled source subclass.

This emits inspection requests, not a link archive. Extra AES method names come
from the explicit source ABI header; live metadata and runtime tests are still
required before treating that interface as usable.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import sys

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--candidate', type=Path, required=True)
p.add_argument('--object', type=Path, required=True)
p.add_argument('--prelink-directory', type=Path, required=True)
p.add_argument('--output', type=Path, required=True)
a = p.parse_args()
sys.path.insert(0, str(a.prelink_directory))
import native_prelink as np

data, obj = a.candidate.read_bytes(), a.object.read_bytes()
plan = json.loads(a.candidate.with_suffix('.json').read_text())
if hashlib.sha256(data).hexdigest() != plan['candidate_sha256'] or plan['original_sha256'] != '2ec297bac95bcba01046fd0148e97e7e5885c05a6c18827f39f534ba375c1221':
    raise ValueError('Require the exact original iPhone16 candidate')
image, om = np.macho(data), np.macho(obj)
exports = np.exports(data, image)
byname = {n: address for address, names in exports.items() for n in names}

def read(va, size):
    offset = np.backed_offset(image['segments'], va, size, len(data))
    return data[offset:offset + size]

def address_returned(va):
    ad, add, ret = struct.unpack('<3I', read(va, 12))
    if ad & 0x9f00001f != 0x90000000 or add & 0xffc003ff != 0x91000000 or ret != 0xd65f03c0:
        return None
    imm = ((ad >> 5 & 0x7ffff) << 2) | (ad >> 29 & 3)
    if imm & 0x100000:
        imm -= 0x200000
    return (va & ~4095) + imm * 4096 + (add >> 10 & 4095)

command = next(o for c, o, size in om['commands'] if c == 2)
symoff, count, stroff, _ = struct.unpack_from('<4I', obj, command + 8)
symbols = []
for i in range(count):
    name, kind, _, _, value = struct.unpack_from('<IBBHQ', obj, symoff + i * 16)
    symbols.append((obj[stroff + name:obj.index(b'\0', stroff + name)].decode(), value, kind))
own_table = next(value for name, value, kind in symbols if name == '__ZTV9NativeAES')
relocs = {}
for segment in om['segments']:
    for sec in segment['sections']:
        if sec['va'] <= own_table < sec['va'] + sec['size']:
            offset, count = struct.unpack_from('<II', obj, sec['command_offset'] + 56)
            for i in range(count):
                address, word = struct.unpack_from('<II', obj, offset + i * 8)
                if word >> 27 & 1 and word >> 28 == 0 and word >> 25 & 3 == 3:
                    relocs[sec['va'] + address] = symbols[word & 0xffffff][0]
names = []
while own_table + 16 + len(names) * 8 in relocs:
    names.append(relocs[own_table + 16 + len(names) * 8])
if len(names) != 181:
    raise ValueError('Unexpected compiled source subclass method count')
algorithm_slot = names.index('__ZN9NativeAES16getAlgorithmNameEv')
extents = [e for e in plan['extents'] if e['module'] == 'com.apple.iokit.IOCryptoAcceleratorFamily']
text = next(e for e in extents if e['segment'] == '__TEXT_EXEC')
const = next(e for e in extents if e['segment'] == '__DATA_CONST')
tables = []
for offset in range(0, const['size'] - (len(names) + 2) * 8, 8):
    va = const['va'] + offset
    if read(va, 16) != bytes(16):
        continue
    target, = struct.unpack('<Q', read(va + 16 + algorithm_slot * 8, 8))
    if not text['va'] <= target < text['va'] + text['size'] - 12:
        continue
    name = address_returned(target)
    if name and read(name, 8) == b'AES-CBC\0':
        tables.append(va)
if len(tables) != 1:
    raise ValueError('Cannot uniquely identify the actual original AES table')
table = tables[0]
own_slots = {0, 1, 7, 86, 111, 117, 168, 169, 170, 171, 172}
rows, mismatches, bindings = [], [], {}
for slot, name in enumerate(names):
    target, = struct.unpack('<Q', read(table + 16 + slot * 8, 8))
    row = {'slot': slot, 'compiled_name': name, 'original_target': hex(target),
           'kernel_names': exports.get(target, []), 'overridden_by_source': slot in own_slots}
    if slot not in own_slots:
        if 'IOAESAccelerator' in name:
            if not text['va'] <= target < text['va'] + text['size']:
                raise ValueError('Original AES method is outside its genuine executable extent')
            bindings[name] = target
            row['annotation'] = 'Name inferred from explicit source ABI header at the measured slot'
        elif name not in row['kernel_names']:
            mismatches.append(row)
    rows.append(row)
meta = address_returned(int(rows[7]['original_target'], 16))
if meta is None:
    raise ValueError('Original getMetaClass does not return a measurable static object')
constructors = []
for va in range(text['va'], text['va'] + text['size'] - 32, 4):
    ins = struct.unpack('<8I', read(va, 32))
    if (ins[:2] != (0xa9bf7bfd, 0x910003fd) or ins[2] & 0xfc000000 != 0x94000000 or
            ins[3] & 0x9f00001f != 0x90000008 or ins[4] & 0xffc003ff != 0x91000108 or
            ins[5:] != (0xf9000008, 0xa8c17bfd, 0xd65f03c0)):
        continue
    imm = ((ins[3] >> 5 & 0x7ffff) << 2) | (ins[3] >> 29 & 3)
    if imm & 0x100000:
        imm -= 0x200000
    vptr = ((va + 12) & ~4095) + imm * 4096 + (ins[4] >> 10 & 4095)
    if vptr == table + 16:
        constructors.append(va)
report = {'candidate_sha256': plan['candidate_sha256'], 'original_sha256': plan['original_sha256'],
          'compiled_object_sha256': hashlib.sha256(obj).hexdigest(), 'vtable': hex(table),
          'algorithm_slot': algorithm_slot, 'methods': rows, 'inherited_mismatches': mismatches,
          'protected_constructor_candidates': [hex(v) for v in constructors],
          'actual_metaclass': hex(meta), 'native_ioservice_metaclass': hex(byname['__ZN9IOService10gMetaClassE']),
          'potential_bindings': {n: hex(v) for n, v in bindings.items()},
          'read_memory': [f'{meta:x}:40', f'{byname["__ZN9IOService10gMetaClassE"]:x}:40'],
          'read_indirect': [f'{meta + 0x10:x}:0:40'],
          'live_instance_sizes_qualified': False, 'bindings_emitted': False,
          'code_modified': False, 'original_hardware_keys_available': False}
a.output.parent.mkdir(parents=True, exist_ok=True)
a.output.write_text(json.dumps(report, indent=2) + '\n')
print(json.dumps({k: v for k, v in report.items() if k not in ['methods', 'potential_bindings']}, indent=2))
