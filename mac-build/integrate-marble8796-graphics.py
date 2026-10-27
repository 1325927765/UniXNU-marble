"""Adapt the reference software IOSurface/framebuffer drivers for marble QEMU."""
from pathlib import Path
import sys


def extract_new_files(patch: str) -> dict[str, str]:
    files = {}
    target = None
    lines = []
    new_file = False
    for line in patch.splitlines(keepends=True):
        if line.startswith('--- '):
            if target and new_file:
                files[target] = ''.join(lines)
            new_file = line.startswith('--- /dev/null')
            target = None
            lines = []
        elif line.startswith('+++ b/'):
            target = line[6:].strip()
        elif target and new_file and line.startswith('+') and not line.startswith('+++'):
            lines.append(line[1:])
    if target and new_file:
        files[target] = ''.join(lines)
    return files


def replace_once(source: str, old: str, new: str, name: str) -> str:
    if source.count(old) != 1:
        raise RuntimeError(f'{name}: expected exactly one insertion point, got {source.count(old)}')
    return source.replace(old, new, 1)


def main():
    patch_file = Path(sys.argv[1]).resolve()
    xnu = Path(sys.argv[2]).resolve()
    patch = patch_file.read_text()
    files = extract_new_files(patch)
    expect = {'NegroniSurface.h', 'NegroniSurface.cpp', 'NegroniFramebuffer.cpp'}
    assert {Path(p).name for p in files} == expect
    for old_path, content in files.items():
        path = xnu / old_path.replace('Negroni', 'Marble')
        adapted = content.replace('NEGRONI', 'MARBLE').replace('Negroni', 'Marble').replace('negroni', 'marble')
        if path.exists() and path.read_text() != adapted:
            raise RuntimeError(f'refusing to overwrite modified {path}')
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(adapted)
        print(path, len(adapted))

    files_arm = xnu / 'iokit/conf/files.arm64'
    source = files_arm.read_text()
    if 'MarbleSurface.cpp' not in source:
        key = 'iokit/Kernel/arm/MarbleEntitlements.cpp'
        line = next(x for x in source.splitlines(keepends=True) if x.startswith(key))
        addition = ('iokit/Kernel/arm/MarbleSurface.cpp                              optional iokitcpp\n'
                    'iokit/Kernel/arm/MarbleFramebuffer.cpp                          optional iokitcpp\n')
        source = replace_once(source, line, line + addition, str(files_arm))
        files_arm.write_text(source)

    table = xnu / 'iokit/KernelConfigTables.cpp'
    source = table.read_text()
    if "'IOCoreSurfaceRoot'" not in source and "= IOCoreSurfaceRoot;" not in source:
        marker = '#if defined(ARM64_BOARD_CONFIG_MARBLE)'
        start = source.index(marker)
        end = source.index('#endif', start)
        block = source[start:end]
        entries = '''    "   {"
    "     'IOClass'         = IOCoreSurfaceRoot;"
    "     'IOProviderClass' = IOResources;"
    "     'IOMatchCategory' = IOCoreSurfaceRoot;"
    "   },"
    "   {"
    "     'IOClass'         = AppleCLCD;"
    "     'IOProviderClass' = IOPlatformDevice;"
    "     'IONameMatch'     = 'marble,display';"
    "   },"
'''
        source = source[:end] + entries + source[end:]
        table.write_text(source)

    platform = xnu / 'iokit/Kernel/arm/MarblePlatformExpert.cpp'
    source = platform.read_text()
    if 'IORegistryEntry *armio' not in source:
        marker = '\tcreateNubs(this, IODTFindMatchingEntries(root, kIODTExclusive, excludeList()));\n'
        addition = '''
\t/* Publish /arm-io children as IOPlatformDevice nubs for built-in drivers. */
\tIORegistryEntry *armio = root->childFromPath("arm-io", gIODTPlane);
\tif (armio != NULL) {
\t\tcreateNubs(this, IODTFindMatchingEntries(armio, kIODTExclusive, "('gic')"));
\t\tarmio->release();
\t}
'''
        source = replace_once(source, marker, marker + addition, str(platform))
        platform.write_text(source)


if __name__ == '__main__':
    main()
