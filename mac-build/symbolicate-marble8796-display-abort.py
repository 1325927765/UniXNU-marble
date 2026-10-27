#!/usr/bin/env python3
"""Resolve a captured iOS 16 backboardd abort through dyld local symbols."""
from pathlib import Path
import struct

cache = Path('/private/tmp/ios16-sysos/System/Library/Caches/com.apple.dyld/dyld_shared_cache_arm64.symbols')
image_cache = Path('/private/tmp/ios16-sysos/System/Library/Caches/com.apple.dyld/dyld_shared_cache_arm64')
targets = [
    0x1e7f13198, 0x1f75a55f8, 0x1b362e4b8, 0x1f74ddf54, 0x1f74c2a4c,
    0x1a5655afc, 0x1f74dd424, 0x1f74dd3d4, 0x1b348b794, 0x1b346b7dc,
]

with image_cache.open('rb') as image_stream, cache.open('rb') as stream:
    image_header = image_stream.read(512)
    header = stream.read(512)
    if not image_header.startswith(b'dyld_v1') or not header.startswith(b'dyld_v1'):
        raise SystemExit('unexpected dyld cache header')
    # Offsets verified by mac-build/_remote/cache-symbolication/offsets.c.
    image_text_offset, image_text_count = struct.unpack_from('<QQ', image_header, 288)
    local_offset, local_size = struct.unpack_from('<QQ', header, 72)
    print(f'image_text_offset={image_text_offset:#x} count={image_text_count} '
          f'local_offset={local_offset:#x} local_size={local_size:#x}')
    if image_text_count > 100000 or local_offset + local_size > cache.stat().st_size:
        raise SystemExit('dyld image text/local symbol table is out of bounds')

    image_text = []
    stream.seek(image_text_offset)
    for _ in range(image_text_count):
        _uuid, load, text_size, path_offset = struct.unpack('<16sQII', stream.read(32))
        image_text.append((load, load + text_size, path_offset))
    if image_text:
        print('first image-text entries:', image_text[:3])
        print('image-text range:', hex(min(x[0] for x in image_text)),
              hex(max(x[1] for x in image_text)))

    # Resolve paths from the cache itself where possible.
    paths = {}
    for _start, _end, path_offset in image_text:
        if path_offset in paths:
            continue
        image_stream.seek(path_offset)
        raw = image_stream.read(512).split(b'\0', 1)[0]
        paths[path_offset] = raw.decode(errors='replace') if raw.startswith(b'/') else ''

    stream.seek(local_offset)
    nlist_offset, nlist_count, string_offset, string_size, _entry_offset, _entry_count = \
        struct.unpack('<6I', stream.read(24))
    if nlist_count > 10_000_000 or string_size > 1_000_000_000:
        raise SystemExit('local symbol table has unreasonable dimensions')
    stream.seek(local_offset + string_offset)
    strings = stream.read(string_size)
    stream.seek(local_offset + nlist_offset)
    symbols = stream.read(nlist_count * 16)

for target in targets:
    matches = [(start, end, path) for start, end, path_offset in image_text
               if start <= target < end for path in [paths[path_offset]]]
    if len(matches) != 1:
        print(f'{target:#x}: image matches={len(matches)} {matches[:4]}')
        continue
    start, end, path = matches[0]
    nearest = (0, '')
    for strx, typ, sect, desc, value in struct.iter_unpack('<IBBHQ', symbols):
        if start <= value <= target and value > nearest[0] and 0 < strx < len(strings):
            terminator = strings.find(b'\0', strx)
            if terminator >= strx:
                nearest = (value, strings[strx:terminator].decode(errors='replace'))
    print(f'{target:#x}: {path} image={start:#x}-{end:#x} '
          f'{nearest[1]} + {target-nearest[0]:#x}')
