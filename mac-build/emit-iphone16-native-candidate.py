#!/usr/bin/env python3
"""Reproduce the iPhone 20H392 candidate without the retired early-crypto code."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

NATIVE = 'e530ba77fb2cb80c89c7a625669716849bff7fefb43ec3d3ac1d6c143538555a'
ORIGINAL = '2ec297bac95bcba01046fd0148e97e7e5885c05a6c18827f39f534ba375c1221'
ROOTS = ['com.apple.filesystems.apfs', 'com.apple.iokit.IOStorageFamily',
         'com.apple.driver.AppleMobileFileIntegrity',
         'com.apple.AppleFSCompression.AppleFSCompressionTypeZlib']
AMFI = 'com.apple.driver.AppleMobileFileIntegrity'
# Pinned original no-argument initializer called by the original service start.
# Entry ignores incoming arguments; its internal registration helper takes a
# boolean and is deliberately NOT used as a void(void) entry.
AMFI_INIT = 0xfffffff005703c54


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--kernel', type=Path, required=True)
    p.add_argument('--original', type=Path, required=True)
    p.add_argument('--prelink-directory', type=Path, required=True)
    p.add_argument('--static-range-tool', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    if a.output.exists() or a.output.with_suffix('.json').exists():
        p.error('Refusing to overwrite an existing experiment')
    native, original = a.kernel.read_bytes(), a.original.read_bytes()
    if hashlib.sha256(native).hexdigest() != NATIVE or hashlib.sha256(original).hexdigest() != ORIGINAL:
        raise ValueError('Require the exact audited native kernel and iPhone 20H392 input')
    sys.path.insert(0, str(a.prelink_directory))
    import native_prelink as np
    import emit_prelink
    spec = importlib.util.spec_from_file_location('static_range', a.static_range_tool)
    placement = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(placement)
    exports = {n for names in np.exports(native, np.macho(native)).values() for n in names}
    if any(n.startswith('_mockfs_') or n.startswith('_source_corecrypto14_') or
           n == '_marble_iphone16_crypto_boot' for n in exports):
        raise ValueError('Refuse fixture filesystem, duplicate crypto provider or retired bootstrap')
    image, report = emit_prelink.emit(native, original, ROOTS, 0x08000000, {AMFI: AMFI_INIT})
    image, report = placement.place(np, image, report)
    a.output.parent.mkdir(parents=True, exist_ok=True)
    a.output.write_bytes(image)
    a.output.with_suffix('.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({'sha256': report['candidate_sha256'], 'bytes': len(image),
                      'original_component_code_modified': False,
                      'full_runtime_qualified': False}, indent=2))


if __name__ == '__main__':
    main()
