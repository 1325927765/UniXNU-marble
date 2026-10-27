"""Map captured QEMU PCs to the original iOS dyld cache's local symbols."""
from pathlib import Path
import hashlib
import json
import struct

r = Path.home()/'unixnu-marble8796-build/cache-symbolication'
cache = Path('/private/tmp/ios16-sysos/System/Library/Caches/com.apple.dyld/dyld_shared_cache_arm64.symbols')
rows = json.loads((r/'first-crashes.json').read_text())
with cache.open('rb') as f:
    header = f.read(256)
    assert header.startswith(b'dyld_v1')
    offset, size = struct.unpack_from('<QQ',header,72)
    assert offset+size <= cache.stat().st_size
    f.seek(offset)
    nlist_offset,nlist_count,string_offset,string_size,entry_offset,entry_count = struct.unpack('<6I',f.read(24))
    assert nlist_count < 10000000 and string_size < 1000000000
    assert nlist_offset+nlist_count*16 <= size
    assert string_offset+string_size <= size
    f.seek(offset+string_offset)
    strings = f.read(string_size)
    f.seek(offset+nlist_offset)
    symbols = f.read(nlist_count*16)
for row in rows:
    assert len(row['matches']) == 1
    base = int(row['matches'][0]['image_base'],16)
    pc = int(row['unslid'],16)
    best = (0,'')
    for strx,typ,sect,desc,value in struct.iter_unpack('<IBBHQ',symbols):
        if base <= value <= pc and value > best[0] and 0 < strx < len(strings):
            end = strings.find(b'\0',strx)
            assert end >= strx
            best = (value,strings[strx:end].decode(errors='replace'))
    row['nearest_local_symbol'] = dict(name=best[1],address=hex(best[0]),offset=hex(pc-best[0]),
                                       exact_function_boundary_proven=False)
report = dict(format_source='https://github.com/apple-oss-distributions/dyld/blob/main/include/mach-o/dyld_cache_format.h',
              inspected_header_sha256=hashlib.sha256((r/'dyld_cache_format.h').read_bytes()).hexdigest(),
              symbol_cache_uuid=header[88:104].hex(),local_symbol_count=nlist_count,
              crash_shared_cache_slide='0x4a62c000',addresses=rows)
(r/'symbolicated-crashes.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report,indent=2))
