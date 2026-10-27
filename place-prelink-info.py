#!/usr/bin/env python3
"""Place prelink metadata after all static segments, within XNU's slid range.

The original emitter places it after native segments only. On ARM64 XNU derives
vm_kernel_slid_top from the end of this metadata, so later component segments
would otherwise be rejected by ml_static_slide. Only Mach-O metadata changes.
"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import struct


def place(np, data, report):
    if hashlib.sha256(data).hexdigest() != report['candidate_sha256']:
        raise ValueError('Input candidate does not match its exact prelink plan')
    output = bytearray(data)
    mh = np.macho(output)
    info = next(s for s in mh['segments'] if s['name'] == '__PRELINK_INFO')
    top = max(s['va']+s['size'] for s in mh['segments'] if s['size'] and s['name'] != '__PRELINK_INFO')
    new = (top+4095) & ~4095
    old = info['va']
    if new+info['size']-(min(s['va'] for s in mh['segments'] if s['size'])) > 0x10000000-0x200000:
        raise ValueError('Correct static image span exceeds the existing loader window')
    struct.pack_into('<Q', output, info['command_offset']+24, new)
    for section in info['sections']:
        struct.pack_into('<Q', output, section['command_offset']+32, section['va']+new-old)
    for seg in mh['segments']:
        if seg['initprot'] & 4 and output[seg['fileoff']:seg['fileoff']+seg['filesize']] != data[seg['fileoff']:seg['fileoff']+seg['filesize']]:
            raise ValueError('Static metadata placement changed executable bytes')
    for segment in report['coalesced_segments']:
        if segment['name'] == '__PRELINK_INFO':
            segment['va'] = new
    report['prelink_info_static_range_fix'] = {'old_va': hex(old), 'new_va': hex(new),
        'new_slid_top': hex(new+info['size']), 'component_end': hex(top),
        'original_executable_bytes_changed': False}
    report['candidate_sha256'] = hashlib.sha256(output).hexdigest()
    return bytes(output), report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--prelink-tool', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists() or args.output.with_suffix('.json').exists():
        parser.error('Refusing to overwrite an existing candidate')
    spec = importlib.util.spec_from_file_location('np', args.prelink_tool)
    np = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(np)
    report = json.loads(args.input.with_suffix('.json').read_text())
    data, report = place(np, args.input.read_bytes(), report)
    args.output.write_bytes(data)
    args.output.with_suffix('.json').write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps(report['prelink_info_static_range_fix'], indent=2))


if __name__ == '__main__':
    main()
