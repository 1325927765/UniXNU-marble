#!/usr/bin/env python3
"""Build the two generic ARM drivers using this XNU build's C++ ABI record.

The compile-record approach follows UniXNU-sheng's build-arm-driver.py
(Git blob e14e0b64f2ef18823598c1818bf20e5720a38b47). This implementation
selects only ArmDTPlatform and ArmCpu; it contains no sheng board resources.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import struct
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('component', choices=['ArmDTPlatform', 'ArmCpu', 'NativeAES'])
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    source = root / 'drivers' / args.component / (args.component + '.cpp')
    if args.component == 'NativeAES':
        source = source.resolve()
    recipe = root / 'build/xnu/ios-obj/DEVELOPMENT_ARM64_BCM2837/iokit/DEVELOPMENT/IOPlatformExpert.cpo.json'
    record = json.loads(recipe.read_text().strip().rstrip(','))
    out = root / 'build' / {'ArmDTPlatform': 'armdt-platform', 'ArmCpu': 'armcpu', 'NativeAES': 'native-aes'}[args.component]
    out.mkdir(parents=True, exist_ok=True)
    obj = out / (args.component + '.o')
    command = []
    arguments = record['arguments']
    i = 0
    replaced_source = replaced_output = 0
    while i < len(arguments):
        value = arguments[i]
        if value == record['file']:
            command.append(str(source))
            replaced_source += 1
        elif value == '-o':
            command += ['-o', str(obj)]
            replaced_output += 1
            i += 1
        elif value == '-Xclang' and i + 1 < len(arguments) and arguments[i + 1].startswith('-W'):
            i += 1
        elif not value.startswith('-W'):
            command.append(value)
        i += 1
    if (replaced_source, replaced_output) != (1, 1):
        raise SystemExit('Compile record must identify exactly one source and output')
    command += ['-Wall', '-Wextra', '-Werror', '-Wno-unused-parameter',
                '-Wno-c99-designator', '-Wno-reorder-init-list',
                '-Wno-deprecated-enum-enum-conversion', '-Wno-unnecessary-virtual-specifier',
                '-I', str(root / '.cache/xnu-work/osfmk')]
    (out / 'compile-command.json').write_text(json.dumps(command, indent=2) + '\n')
    with (out / 'compile.log').open('w') as log:
        subprocess.run(command, cwd=record['directory'], stdout=log, stderr=subprocess.STDOUT, check=True)
    data = obj.read_bytes()
    if len(data) < 32 or struct.unpack_from('<4I', data) != (0xfeedfacf, 0x100000c, 0, 1):
        raise SystemExit('Expected ordinary ARM64 Mach-O object')
    cursor = 32
    deployment = None
    for _ in range(struct.unpack_from('<I', data, 16)[0]):
        cmd, length = struct.unpack_from('<II', data, cursor)
        if length < 8 or cursor + length > len(data):
            raise SystemExit('Malformed Mach-O load command')
        if cmd == 0x32:
            deployment = struct.unpack_from('<II', data, cursor + 8)
        cursor += length
    if deployment != (2, 0x110000):
        raise SystemExit(f'Expected iOS 17.0 object, got {deployment}')
    archive = out / ('lib' + args.component + '.a')
    archive.unlink(missing_ok=True)
    objects = [str(obj)]
    if args.component == 'NativeAES':
        bindings = json.loads(Path(os.environ['XNU_IPHONE16_AES_BINDINGS']).read_text())
        if (bindings['original_sha256'] != '2ec297bac95bcba01046fd0148e97e7e5885c05a6c18827f39f534ba375c1221' or
                not bindings['live_instance_sizes_qualified'] or bindings['other_device_recorded_bindings_used'] or
                bindings['compiled_subclass_slots_checked'] != 181 or bindings['inherited_slot_mismatches']):
            raise ValueError('Require measured iPhone16 software-AES bindings')
        if (hashlib.sha256(source.read_bytes()).hexdigest() != bindings['source_cpp_sha256'] or
                hashlib.sha256(source.with_name('OriginalAESABI.h').read_bytes()).hexdigest() != bindings['source_header_sha256']):
            raise ValueError('Pinned AES source or header differs')
        sys.path.insert(0, str(root / 'kits/NativePrelink'))
        import native_prelink as np
        parsed = np.macho(data)
        text = next(s for seg in parsed['segments'] for s in seg['sections'] if s['name'] == '__text')
        if hashlib.sha256(data[text['fileoff']:text['fileoff']+text['size']]).hexdigest() != bindings['compiled_text_sha256']:
            raise ValueError('Actual source subclass instructions differ from the audited object')
        asm = out / 'iphone16-original-bindings.S'
        for name, value in bindings['bindings'].items():
            if not name.replace('_', '').isalnum() or int(value, 16) & 3:
                raise ValueError('Unexpected measured symbol binding')
        asm.write_text(''.join(f'.globl {n}\n.set {n}, {int(v, 16):#x}\n' for n, v in sorted(bindings['bindings'].items())))
        bound = out / 'iphone16-original-bindings.o'
        subprocess.run(['xcrun', 'clang', '-target', 'arm64-apple-ios17.0', '-Werror',
                        '-Wno-incompatible-sysroot', '-c', str(asm), '-o', str(bound)], check=True)
        objects.append(str(bound))
        (out / 'iphone16-bindings.json').write_text(json.dumps(bindings, indent=2)+'\n')
    subprocess.run(['xcrun', 'ar', 'rcs', str(archive), *objects], check=True)
    (out / 'build-report.json').write_text(json.dumps({
        'component': args.component,
        'source_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
        'archive_sha256': hashlib.sha256(archive.read_bytes()).hexdigest(),
        'target': 'arm64-apple-ios17.0', 'runtime_observed': False,
    }, indent=2) + '\n')


if __name__ == '__main__':
    main()
