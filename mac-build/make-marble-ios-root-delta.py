"""Pack changed 1 MiB ranges between two same-sized raw HFS images."""
import argparse
import hashlib
import json
import struct
from pathlib import Path

MAGIC = b"MRBDLT1\0"
HEADER = struct.Struct("<8sQQQ")
RECORD = struct.Struct("<QI")

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("base", type=Path)
parser.add_argument("modified", type=Path)
parser.add_argument("delta", type=Path)
parser.add_argument("--chunk-size", type=int, default=1024 * 1024)
args = parser.parse_args()
base = args.base.resolve()
modified = args.modified.resolve()
if base.stat().st_size != modified.stat().st_size:
    raise SystemExit("base and modified images have different sizes")
if args.chunk_size < 4096 or args.chunk_size > 16 * 1024 * 1024:
    raise SystemExit("chunk size must be between 4 KiB and 16 MiB")

size = base.stat().st_size
count = 0
base_digest = hashlib.sha256()
modified_digest = hashlib.sha256()
with base.open("rb") as a, modified.open("rb") as b, args.delta.open("wb") as out:
    out.write(HEADER.pack(MAGIC, size, args.chunk_size, 0))
    offset = 0
    while offset < size:
        left = a.read(args.chunk_size)
        right = b.read(args.chunk_size)
        base_digest.update(left)
        modified_digest.update(right)
        if left != right:
            out.write(RECORD.pack(offset, len(right)))
            out.write(right)
            count += 1
        offset += len(left)
    out.write(RECORD.pack((1 << 64) - 1, 0))
    out.seek(0)
    out.write(HEADER.pack(MAGIC, size, args.chunk_size, count))

def sha(path):
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()

report = {
    "base_sha256": base_digest.hexdigest(),
    "modified_sha256": modified_digest.hexdigest(),
    "delta_sha256": sha(args.delta),
    "image_bytes": size,
    "chunk_size": args.chunk_size,
    "changed_chunks": count,
    "delta_bytes": args.delta.stat().st_size,
}
args.delta.with_suffix(args.delta.suffix + ".json").write_text(json.dumps(report, indent=2) + "\n")
print(json.dumps(report, indent=2))
