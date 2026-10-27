#!/usr/bin/env python3
"""Decode an unchanged iPhone IM4P and audit its architecture/source version.

Runs on macOS (compression_tool). Header acceptance is not a prelink/ABI proof.
"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import struct
import subprocess


def payload(data):
    def der(at):
        if at + 2 > len(data):
            raise ValueError('Truncated DER')
        tag, size = data[at:at+2]
        at += 2
        if size & 128:
            count = size & 127
            if not 0 < count <= 8 or at + count > len(data):
                raise ValueError('Invalid DER size')
            size = int.from_bytes(data[at:at+count], 'big')
            at += count
        if at + size > len(data):
            raise ValueError('DER exceeds input')
        return tag, at, size
    tag, at, size = der(0)
    if tag != 0x30 or at + size != len(data):
        raise ValueError('Expected exactly one IM4P sequence')
    end, items = at + size, []
    while at < end:
        tag, start, size = der(at)
        items.append((tag, data[start:start+size]))
        at = start + size
    if len(items) < 4 or items[0][1] != b'IM4P' or items[1][1] != b'krnl' or items[3][0] != 4:
        raise ValueError('Input is not a kernel IM4P')
    return items[3][1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--prelink-tool', type=Path, required=True)
    parser.add_argument('--source-version', default='10063.141.1')
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    original = args.input.read_bytes()
    compressed = args.output / 'kernelcache.lzfse'
    fat = args.output / 'kernelcache.fat'
    compressed.write_bytes(payload(original))
    subprocess.run(['/usr/bin/compression_tool', '-decode', '-a', 'lzfse', '-i', compressed, '-o', fat], check=True)
    data = fat.read_bytes()
    if data[:4] == b'\xca\xfe\xba\xbe':
        count = struct.unpack_from('>I', data, 4)[0]
        if count > 32 or 8 + count * 20 > len(data):
            raise ValueError('Invalid FAT header')
        slices = [struct.unpack_from('>5I', data, 8+i*20) for i in range(count)]
        arm64 = [s for s in slices if s[0] == 0x100000c]
        if len(arm64) != 1:
            raise ValueError('Expected exactly one ARM64 slice')
        _, _, offset, size, _ = arm64[0]
        if offset + size > len(data):
            raise ValueError('FAT slice exceeds input')
        data = data[offset:offset+size]
    header = struct.unpack_from('<8I', data)
    if header[0] != 0xfeedfacf:
        raise ValueError('Not a Mach-O kernelcache')
    destination = args.output / 'kernelcache.macho'
    destination.write_bytes(data)
    spec = importlib.util.spec_from_file_location('native_prelink', args.prelink_tool)
    native = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(native)
    accepted, refusal = True, None
    try:
        native.macho(data)
    except ValueError as error:
        accepted, refusal = False, str(error)
    versions = sorted(set(v.decode() for v in re.findall(rb'Darwin Kernel Version[^\0\n]{1,300}', data)))
    source_match = bool(versions) and all(f'xnu-{args.source_version}~' in v for v in versions)
    report = {'input_im4p_sha256': hashlib.sha256(original).hexdigest(),
        'kernelcache_sha256': hashlib.sha256(data).hexdigest(), 'kernelcache_bytes': len(data),
        'mach_header': dict(zip(['magic', 'cpu_type', 'cpu_subtype', 'file_type', 'commands', 'command_bytes', 'flags', 'reserved'], header)),
        'darwin_versions': versions, 'current_source_version': args.source_version,
        'exact_source_version_match': source_match, 'ordinary_arm64_header_accepted': accepted,
        'prelink_header_refusal': refusal, 'prelink_tool_sha256': hashlib.sha256(args.prelink_tool.read_bytes()).hexdigest(),
        'full_component_abi_qualified': False, 'ios_userspace_boot_demonstrated': False,
        'original_input_modified': args.input.read_bytes() != original}
    (args.output / 'kernel-qualification.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
