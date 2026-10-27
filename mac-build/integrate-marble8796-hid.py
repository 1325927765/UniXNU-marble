"""Stage reference HID event services and a bounded opt-in Home test.

This does not implement the F5 touch controller. Dry-run unless --apply.
"""
from pathlib import Path
from datetime import datetime
import argparse
import hashlib
import json
import importlib.util


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--patch', type=Path, required=True)
    p.add_argument('--source-root', type=Path, required=True)
    p.add_argument('--apply', action='store_true')
    a = p.parse_args()
    spec = importlib.util.spec_from_file_location('graphics', Path(__file__).with_name('integrate-marble8796-graphics.py'))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    files = mod.extract_new_files(a.patch.read_text(encoding='latin-1'))
    assert len(files) == 31, len(files)
    staged = {}
    for name, source in files.items():
        assert name.startswith('iokit/Kernel/arm/hid/') and '..' not in Path(name).parts
        name = name.replace('Sweet', 'Marble')
        source = source.replace('SWEET', 'MARBLE').replace('Sweet', 'Marble').replace('sweet', 'marble')
        source = source.replace('packed,,aligned(4)', 'packed,aligned(4)')
        if name.endswith('/MarbleHID.cpp'):
            # Three paired Home presses; never an unbounded input loop.
            source = source.replace('fTestCount < 60', 'fTestCount < 6')
            source = source.replace('&& fTestSecs) {', '&& fTestSecs >= 30 && fTestSecs <= 300) {')
            source = source.replace('every N seconds, to test', 'every N seconds (30..300, three presses), to test')
            assert 'fTestCount < 6' in source and 'fTestSecs <= 300' in source
        staged[name] = source
    r = a.source_root
    old = {}
    for name in staged:
        assert not (r/name).exists(), f'Refusing to overwrite {name}'
    for name in ('iokit/conf/files.arm64', 'iokit/KernelConfigTables.cpp'):
        old[name] = (r/name).read_text()
    assert 'MarbleHID' not in old['iokit/conf/files.arm64']
    staged['iokit/conf/files.arm64'] = old['iokit/conf/files.arm64'] + '\n' + ''.join(
        f'iokit/Kernel/arm/hid/{name}.cpp optional iokitcpp\n' for name in
        ('MarbleHID', 'IOHIDEvent', 'IOHIDEventServiceQueue', 'IOHIDEventServiceUserClient'))
    name = 'iokit/KernelConfigTables.cpp'
    s = old[name]
    marker = '#if defined(ARM64_BOARD_CONFIG_MARBLE)'
    assert s.count(marker) == 1 and 'MarbleHIDButtons' not in s
    end = s.index('#endif', s.index(marker))
    entries = ''
    for cls in ('MarbleHIDButtons', 'MarbleHIDTouch'):
        entries += ('    "   {"\n'
                    f'    "     \'IOClass\' = {cls};"\n'
                    '    "     \'IOProviderClass\' = IOResources;"\n'
                    f'    "     \'IOMatchCategory\' = {cls};"\n'
                    '    "   },"\n')
    staged[name] = s[:end] + entries + s[end:]
    print('Validated 31 HID files, four compilation units, two Marble personalities; Home test max three presses')
    if not a.apply:
        return
    backup = r/'trace-backups'/datetime.now().strftime('%Y%m%d-hid-%H%M%S')
    backup.mkdir(parents=True, exist_ok=False)
    for name, source in old.items():
        dest = backup/name
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(source)
    for name, source in staged.items():
        dest = r/name
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(source)
    manifest = {'reference_patch_sha256': hashlib.sha256(a.patch.read_bytes()).hexdigest(),
                'new_files': sorted(set(staged)-set(old)),
                'files': {name: hashlib.sha256(source.encode()).hexdigest() for name, source in staged.items()},
                'touch_controller_implemented': False, 'home_boot_arg': 'marblehidtest',
                'max_home_presses': 3, 'home_press_ms': 100}
    (backup/'manifest.json').write_text(json.dumps(manifest, indent=2)+'\n')
    print('Applied; backup:', backup)


if __name__ == '__main__':
    main()
