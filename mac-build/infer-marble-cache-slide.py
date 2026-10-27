#!/usr/bin/env python3
"""Infer a QEMU dyld shared-cache slide from an iOS exception frame."""
from pathlib import Path
import struct
import sys

cache_path, symbols_path = map(Path, sys.argv[1:3])
pcs = [int(x, 0) for x in sys.argv[3:]]
cache = cache_path.read_bytes()
assert cache.startswith(b"dyld_v1")
images_off, images_count = struct.unpack_from("<QQ", cache, 288)
assert images_count < 100000 and images_off + images_count * 32 <= len(cache)
images = []
for i in range(images_count):
    off = images_off + i * 32
    _uuid, base, size, path_off = struct.unpack_from("<16sQII", cache, off)
    end = cache.find(b"\0", path_off)
    images.append((base, base + size, cache[path_off:end].decode(errors="replace")))
with symbols_path.open("rb") as f:
    h = f.read(256)
    local_off, local_size = struct.unpack_from("<QQ", h, 72)
    f.seek(local_off)
    nl_off, nl_count, st_off, st_size, _, _ = struct.unpack("<6I", f.read(24))
    f.seek(local_off + st_off)
    strings = f.read(st_size)
    f.seek(local_off + nl_off)
    nlists = f.read(nl_count * 16)
symbols = []
for strx, typ, sect, desc, value in struct.iter_unpack("<IBBHQ", nlists):
    if strx and strx < len(strings):
        end = strings.find(b"\0", strx)
        if end > strx:
            name = strings[strx:end].decode(errors="replace")
            if "initFileURLWithPath" in name:
                symbols.append((value, name))
print("URL initializer candidates:")
for value, name in symbols[:80]:
    print(hex(value), name)
if not symbols:
    raise SystemExit("no local NSURL initializer symbol found")
target = pcs[0]
candidates = set()
for value, name in symbols:
    for offset in range(0, 0x1000, 4):
        slide = target - (value + offset)
        if slide >= 0 and slide % 0x4000 == 0:
            candidates.add(slide)
for slide in sorted(candidates):
    if not (0x10000000 <= slide <= 0x80000000):
        continue
    matched = []
    for pc in pcs:
        addr = pc - slide
        image = next((x for x in images if x[0] <= addr < x[1]), None)
        if not image:
            matched.append((pc, "NO IMAGE", ""))
            continue
        base, _, path = image
        best = (0, "")
        for strx, typ, sect, desc, value in struct.iter_unpack("<IBBHQ", nlists):
            if base <= value <= addr and value > best[0] and 0 < strx < len(strings):
                end = strings.find(b"\0", strx)
                if end > strx:
                    best = (value, strings[strx:end].decode(errors="replace"))
        matched.append((pc, path, f"{best[1]}+{addr-best[0]:#x}"))
    score = sum(1 for pc, path, sym in matched if path != "NO IMAGE")
    # Prioritize a slide that maps the presumed exception PC into Foundation.
    if score >= len(pcs) - 2:
        print(f"\nslide={slide:#x} mapped={score}/{len(pcs)}")
        for pc, path, sym in matched:
            print(f"{pc:#x} {path} {sym}")
