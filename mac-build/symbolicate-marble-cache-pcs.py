"""Resolve shared-cache frames using iOS dyld cache image text and local symbols."""
from pathlib import Path
import struct
import sys

cache = Path(sys.argv[1])
symbols_file = Path(sys.argv[2])
slide = int(sys.argv[3], 0)
pcs = [int(value, 0) for value in sys.argv[4:]]
header = cache.read_bytes()
assert header.startswith(b"dyld_v1")
images_offset, images_count = struct.unpack_from("<QQ", header, 136)
assert images_count < 100000 and images_offset + images_count * 32 <= len(header)
images = []
for i in range(images_count):
    off = images_offset + i * 32
    _, base, size, path_off = struct.unpack_from("<16sQII", header, off)
    assert path_off < len(header)
    end = header.find(b"\0", path_off)
    path = header[path_off:end].decode(errors="replace")
    images.append((base, base + size, path))

with symbols_file.open("rb") as f:
    h = f.read(256)
    local_off, local_size = struct.unpack_from("<QQ", h, 72)
    assert local_off + local_size <= symbols_file.stat().st_size
    f.seek(local_off)
    nlist_offset, nlist_count, string_offset, string_size, _, _ = struct.unpack("<6I", f.read(24))
    assert nlist_count < 10_000_000 and string_size < 1_000_000_000
    f.seek(local_off + string_offset)
    strings = f.read(string_size)
    f.seek(local_off + nlist_offset)
    nlists = f.read(nlist_count * 16)

for pc in pcs:
    addr = pc - slide
    match = next((x for x in images if x[0] <= addr < x[1]), None)
    if not match:
        print(hex(pc), "unslid", hex(addr), "image NOT FOUND")
        continue
    base, _, path = match
    best = (0, "")
    for strx, typ, sect, desc, value in struct.iter_unpack("<IBBHQ", nlists):
        if base <= value <= addr and value > best[0] and 0 < strx < len(strings):
            end = strings.find(b"\0", strx)
            if end >= strx:
                best = (value, strings[strx:end].decode(errors="replace"))
    print(hex(pc), "unslid", hex(addr), path, "image", hex(base),
          "symbol", best[1], hex(best[0]), "+", hex(addr - best[0]))
