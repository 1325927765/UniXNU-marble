#!/usr/bin/env python3
"""Print selected local dyld-cache symbols for a crash investigation."""
from pathlib import Path
import struct
import sys

path = Path(sys.argv[1])
terms = tuple(x.lower() for x in sys.argv[2:])
with path.open("rb") as f:
    h = f.read(256)
    local_off, local_size = struct.unpack_from("<QQ", h, 72)
    if local_off + local_size > path.stat().st_size:
        raise SystemExit("local symbol table out of bounds")
    f.seek(local_off)
    nlist_off, nlist_count, string_off, string_size, _, _ = struct.unpack("<6I", f.read(24))
    f.seek(local_off + string_off)
    strings = f.read(string_size)
    f.seek(local_off + nlist_off)
    nlists = f.read(nlist_count * 16)
for strx, typ, sect, desc, value in struct.iter_unpack("<IBBHQ", nlists):
    if 0 < strx < len(strings):
        end = strings.find(b"\0", strx)
        if end > strx:
            name = strings[strx:end].decode(errors="replace")
            if any(term in name.lower() for term in terms):
                print(f"{value:#018x} {name}")
