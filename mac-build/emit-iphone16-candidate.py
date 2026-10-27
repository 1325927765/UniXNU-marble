#!/usr/bin/env python3
"""Emit the pinned iPhone16 component experiment and its early crypto binding.

Only the native descriptor is filled. Original component instructions and POST
remain unchanged. This is not a runtime or full iOS compatibility certificate.
"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import struct
import sys

ORIGINAL = '2ec297bac95bcba01046fd0148e97e7e5885c05a6c18827f39f534ba375c1221'
CRYPTO = 'com.apple.kec.corecrypto'
ROOTS = ['com.apple.filesystems.apfs', 'com.apple.iokit.IOStorageFamily',
         'com.apple.driver.AppleMobileFileIntegrity']


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--kernel', type=Path, required=True)
    parser.add_argument('--original', type=Path, required=True)
    parser.add_argument('--prelink-directory', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists() or args.output.with_suffix('.json').exists():
        parser.error('Refusing to overwrite an existing experiment')
    sys.path.insert(0, str(args.prelink_directory))
    import native_prelink as np
    import emit_prelink
    native, original = args.kernel.read_bytes(), args.original.read_bytes()
    if hashlib.sha256(original).hexdigest() != ORIGINAL:
        raise ValueError('Only the pinned original iPhone 20H392 kernel is qualified for this descriptor')
    nm = np.macho(native)
    exports = {n: a for a, names in np.exports(native, nm).items() for n in names}
    if '_source_corecrypto14_status' in exports:
        raise ValueError('The source-provider bootstrap must be omitted in this explicit original-provider build')
    marker = exports['_marble_iphone16_crypto_boot']
    image, report = emit_prelink.emit(native, original, ROOTS, 0x08000000)
    header = np.macho(original)
    info = next(s for s in header['segments'] if s['name'] == '__PRELINK_INFO')
    at = np.backed_offset(header['segments'], info['va'], info['filesize'], len(original))
    metadata = np.unserialize_xml(original[at:at+info['filesize']])
    entry = next(e for e in metadata['_PrelinkInfoDictionary'] if e['CFBundleIdentifier'] == CRYPTO)
    if entry['CFBundleVersion'] != '12.0':
        raise ValueError('Unexpected original crypto version')
    if any(not n.startswith('com.apple.kpi.') for n in entry['OSBundleLibraries']):
        raise ValueError('Early crypto has non-kernel dependencies')
    mh = np.macho(original, np.backed_offset(header['segments'], entry['_PrelinkExecutableLoadAddr'], 32, len(original)))
    if any(s['size'] for seg in mh['segments'] for s in seg['sections'] if s['name'] == '__mod_init_func'):
        raise ValueError('Early crypto is not constructor-free')
    text = next(s for s in mh['segments'] if s['name'] == '__TEXT_EXEC')
    data = next(s for s in mh['segments'] if s['name'] == '__DATA')
    if text['initprot'] != 5 or text['maxprot'] & 2:
        raise ValueError('Original crypto lacks immutable executable permissions')
    slide = report['slide']
    module = report['module_entrypoints'][CRYPTO]
    boot = [0x4950313643525950, 1, module['kmod_info_va'], module['start_va'],
        entry['_PrelinkExecutableLoadAddr']+slide, text['va']+slide,
        text['va']+slide+text['size'], data['va']+slide, data['va']+slide+data['size']]
    output = bytearray(image)
    mapped = np.macho(output)
    offset = np.backed_offset(mapped['segments'], marker, 72, len(output))
    if struct.unpack_from('<9Q', output, offset) != (boot[0], 1, 0, 0, 0, 0, 0, 0, 0):
        raise ValueError('Native crypto descriptor does not have its exact unbound initializer')
    kmod = np.backed_offset(mapped['segments'], module['kmod_info_va'], 196, len(output))
    if struct.unpack_from('<Q', output, kmod+156)[0] != boot[4] or struct.unpack_from('<Q', output, kmod+180)[0] != boot[3]:
        raise ValueError('Relocated original kmod identity disagrees with the descriptor')
    struct.pack_into('<9Q', output, offset, *boot)
    for seg in mapped['segments']:
        if seg['initprot'] & 4 and output[seg['fileoff']:seg['fileoff']+seg['filesize']] != image[seg['fileoff']:seg['fileoff']+seg['filesize']]:
            raise ValueError('Descriptor binding modified executable bytes')
    populated = [s for s in mapped['segments'] if s['size']]
    span = max(s['va']+s['size'] for s in populated)-min(s['va'] for s in populated)
    if span > 0x10000000-0x200000:
        raise ValueError('Candidate exceeds the existing DarwinBoot image span')
    report.update(candidate_sha256=hashlib.sha256(output).hexdigest(), candidate_bytes=len(output),
        iphone16_original_crypto_boot={'descriptor_va': hex(marker), 'values': [hex(v) for v in boot],
            'constructor_count': 0, 'original_start_executed_at': 'EARLY_BOOT / FIRST',
            'later_start': 'OSKext adopts only a matching, actually completed original start',
            'original_post_modified': False, 'executable_bytes_modified_by_binding': False},
        loader_image_span=span, original_crypto_runtime_qualified=False)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(output)
    args.output.with_suffix('.json').write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps({'candidate_sha256': report['candidate_sha256'], 'bytes': len(output),
                      'loader_image_span': span, 'early_crypto': report['iphone16_original_crypto_boot']}, indent=2))


if __name__ == '__main__':
    main()
