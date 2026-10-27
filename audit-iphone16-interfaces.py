#!/usr/bin/env python3
"""Inventory every unresolved iPhone kernel binding without emitting a kernel.

Unlike a prelink build, this collects errors rather than stopping at the first
missing symbol. No replacement address is invented and no image is modified.
This pointer/interface inventory is not a C/C++ object-layout qualification.
"""
import argparse
from bisect import bisect_right
from collections import Counter
import hashlib
import importlib.util
import json
from pathlib import Path
import struct


def audit(np, native_data, original_data, roots):
    native, original = np.macho(native_data), np.macho(original_data)
    if native['kind'] != 2 or original['kind'] != 2:
        raise ValueError('Expected two ordinary ARM64 MH_EXECUTE images')
    parent = original['segments']
    info = next(s for s in parent if s['name'] == '__PRELINK_INFO')
    at = np.backed_offset(parent, info['va'], info['filesize'], len(original_data))
    metadata = np.unserialize_xml(original_data[at:at+info['filesize']])
    entries = {}
    for entry in metadata['_PrelinkInfoDictionary']:
        name = entry['CFBundleIdentifier']
        if name in entries:
            raise ValueError('Duplicate bundle identifier')
        entries[name] = entry
    selected, interfaces, pending = set(), set(), list(roots)
    while pending:
        name = pending.pop()
        if name in selected or name in interfaces:
            continue
        if name not in entries:
            raise ValueError(f'Missing dependency {name}')
        entry = entries[name]
        if entry.get('OSKernelResource') is True:
            interfaces.add(name)
        else:
            selected.add(name)
            pending.extend(entry.get('OSBundleLibraries') or {})
    extents = []
    for name, entry in entries.items():
        if entry.get('OSKernelResource') is True or not entry.get('_PrelinkExecutableSize'):
            continue
        address = entry.get('_PrelinkExecutableLoadAddr')
        if address is None:
            continue
        module = np.macho(original_data, np.backed_offset(parent, address, 32, len(original_data)))
        if module['kind'] != 11:
            raise ValueError('Expected MH_KEXT_BUNDLE')
        for segment in module['segments']:
            if segment['size'] and segment['name'] != '__LINKEDIT':
                extents.append((segment['va'], segment['va']+segment['size'], name))
    extents.sort()
    if any(a[1] > b[0] for a, b in zip(extents, extents[1:])):
        raise ValueError('Overlapping component segments')
    starts = [e[0] for e in extents]
    def owner(address):
        i = bisect_right(starts, address)-1
        return extents[i] if i >= 0 and address < extents[i][1] else None
    native_symbols = {}
    for address, names in np.exports(native_data, native).items():
        for name in names:
            native_symbols.setdefault(name, set()).add(address)
    original_symbols = np.exports(original_data, original)
    table = metadata['_PrelinkLinkKASLROffsets']
    count, = struct.unpack_from('<I', table)
    if len(table) != 4+4*count:
        raise ValueError('Invalid pointer-table size')
    offsets = struct.unpack_from(f'<{count}I', table, 4)
    if len(set(offsets)) != count:
        raise ValueError('Duplicate relocation sites')
    base = next(s['va'] for s in parent if s['name'] == '__PRELINK_TEXT')
    issues, counts, module_counts = {}, Counter(), Counter()
    for offset in offsets:
        site = base+offset
        source = owner(site)
        if source is None or source[2] not in selected:
            continue
        if source != owner(site+7):
            raise ValueError('Pointer spans a component extent')
        target, = struct.unpack_from('<Q', original_data, np.backed_offset(parent, site, 8, len(original_data)))
        destination = owner(target)
        if destination:
            counts['component'] += 1
            if destination[2] not in selected:
                raise ValueError(f'Undeclared dependency {destination[2]} from {source[2]}')
            continue
        counts['kernel'] += 1
        module_counts[source[2]] += 1
        try:
            replacement = np.unique_kernel_binding(target, original_symbols, native_symbols)
            if not any(s['va'] <= replacement < s['va']+s['size'] for s in native['segments']):
                raise ValueError('Native export outside mapped segments')
            counts['resolved_kernel'] += 1
        except ValueError as error:
            counts['unresolved_kernel'] += 1
            issue = issues.setdefault(target, {'original_target': hex(target),
                'symbols': sorted(original_symbols.get(target, [])), 'reason': str(error),
                'sites': [], 'modules': set()})
            issue['sites'].append(hex(site))
            issue['modules'].add(source[2])
    unresolved = []
    for issue in issues.values():
        issue['modules'] = sorted(issue['modules'])
        unresolved.append(issue)
    return {'roots': roots, 'components': [{'identifier': n, 'version': entries[n].get('CFBundleVersion'),
        'security_extension': entries[n].get('AppleSecurityExtension', False)} for n in sorted(selected)],
        'kernel_interfaces': sorted(interfaces), 'pointer_counts': dict(counts),
        'kernel_references_by_module': dict(module_counts), 'unresolved_targets': unresolved,
        'unique_unresolved_targets': len(unresolved),
        'native_sha256': hashlib.sha256(native_data).hexdigest(),
        'original_sha256': hashlib.sha256(original_data).hexdigest(),
        'images_modified': False, 'kernel_emitted': False, 'loadable': False,
        'object_layout_qualified': False, 'instruction_relocation_qualified': False,
        'scope': 'Read-only complete pointer-table inventory for the selected dependency closure; no fabricated bindings.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--kernel', type=Path, required=True)
    parser.add_argument('--original', type=Path, required=True)
    parser.add_argument('--prelink-tool', type=Path, required=True)
    parser.add_argument('--root', action='append', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    spec = importlib.util.spec_from_file_location('native_prelink', args.prelink_tool)
    np = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(np)
    report = audit(np, args.kernel.read_bytes(), args.original.read_bytes(), args.root)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps({'components': report['components'], 'pointer_counts': report['pointer_counts'],
        'unique_unresolved_targets': report['unique_unresolved_targets'],
        'missing_symbols': [i['symbols'] for i in report['unresolved_targets']]}, indent=2))


if __name__ == '__main__':
    main()
