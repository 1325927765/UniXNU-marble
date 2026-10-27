#!/usr/bin/env python3
"""Compile the pinned software AES subclass for ABI inspection, without linking."""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import subprocess

PIN = 'a34964b8c2fec2e83c8e4f68fb7d6fb7e4b2227b'
p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--tree', type=Path, required=True)
p.add_argument('--source', type=Path, required=True)
p.add_argument('--output', type=Path, required=True)
a = p.parse_args()
revision = subprocess.check_output(['git', '-C', a.source.parent, 'rev-parse', 'HEAD'], text=True).strip()
if revision != PIN:
    raise ValueError('NativeAES source pin differs')
recipe = a.tree / 'build/xnu/ios-obj/DEVELOPMENT_ARM64_BCM2837/iokit/DEVELOPMENT/IOPlatformExpert.cpo.json'
record = json.loads(recipe.read_text().strip().rstrip(','))
a.output.parent.mkdir(parents=True, exist_ok=True)
command, i, replaced = [], 0, [0, 0]
while i < len(record['arguments']):
    value = record['arguments'][i]
    if value == record['file']:
        command.append(str(a.source)); replaced[0] += 1
    elif value == '-o':
        command += ['-o', str(a.output)]; replaced[1] += 1; i += 1
    elif value == '-Xclang' and i + 1 < len(record['arguments']) and record['arguments'][i + 1].startswith('-W'):
        i += 1
    elif not value.startswith('-W'):
        command.append(value)
    i += 1
if replaced != [1, 1]:
    raise ValueError('Require exactly one source and output in the compiler record')
command += ['-Wall', '-Wextra', '-Werror', '-Wno-unused-parameter', '-Wno-c99-designator',
            '-Wno-reorder-init-list', '-Wno-deprecated-enum-enum-conversion',
            '-Wno-unnecessary-virtual-specifier', '-I', str(a.tree / '.cache/xnu-work/osfmk')]
with a.output.with_suffix('.compile.log').open('w') as log:
    subprocess.run(command, cwd=record['directory'], stdout=log, stderr=subprocess.STDOUT, check=True)
data = a.output.read_bytes()
if struct.unpack_from('<4I', data) != (0xfeedfacf, 0x100000c, 0, 1):
    raise ValueError('Require an ordinary ARM64 Mach-O object')
a.output.with_suffix('.compile.json').write_text(json.dumps({
    'source_commit': PIN, 'source_sha256': hashlib.sha256(a.source.read_bytes()).hexdigest(),
    'object_sha256': hashlib.sha256(data).hexdigest(), 'compile_command': command,
    'linked': False, 'bindings_emitted': False, 'iphone16_abi_qualified': False,
    'uses_recorded_other_device_bindings': False}, indent=2) + '\n')
print('Compiled ordinary ARM64 NativeAES object for inspection; no original methods bound or kernel linked')
