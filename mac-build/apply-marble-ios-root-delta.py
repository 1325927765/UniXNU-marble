"""Apply a checked HFS image delta to a new copy of the expected base image."""
import argparse
import hashlib
import shutil
import struct
from pathlib import Path

MAGIC = b"MRBDLT1\0"
HEADER = struct.Struct("<8sQQQ")
RECORD = struct.Struct("<QI")

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("base", type=Path)
parser.add_argument("delta", type=Path)
parser.add_argument("output", type=Path)
parser.add_argument("--base-sha256", required=True)
args = parser.parse_args()
base = args.base.resolve()
delta = args.delta.resolve()
output = args.output.resolve()
if output.exists():
    raise SystemExit(f"refusing to overwrite existing output: {output}")

def sha(path):
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()

actual_base = sha(base)
if actual_base.lower() != args.base_sha256.lower():
    raise SystemExit(f"base hash mismatch: {actual_base}")

with delta.open("rb") as patch:
    header = patch.read(HEADER.size)
    if len(header) != HEADER.size:
        raise SystemExit("truncated delta header")
    magic, image_size, chunk_size, expected_count = HEADER.unpack(header)
    if magic != MAGIC or image_size != base.stat().st_size:
        raise SystemExit("delta does not match base image format/size")
    if chunk_size < 4096 or chunk_size > 16 * 1024 * 1024:
        raise SystemExit("invalid delta chunk size")
    previous_end = 0
    preflight_count = 0
    while True:
        raw = patch.read(RECORD.size)
        if len(raw) != RECORD.size:
            raise SystemExit("truncated delta record")
        offset, length = RECORD.unpack(raw)
        if offset == (1 << 64) - 1:
            if length != 0 or preflight_count != expected_count or patch.read(1):
                raise SystemExit("invalid delta terminator/count")
            break
        if length == 0 or length > chunk_size or offset < previous_end or offset + length > image_size:
            raise SystemExit("invalid or overlapping delta range")
        if len(patch.read(length)) != length:
            raise SystemExit("truncated delta data")
        previous_end = offset + length
        preflight_count += 1

shutil.copyfile(base, output)
with delta.open("rb") as patch:
    patch.seek(HEADER.size)
    previous_end = 0
    count = 0
    with output.open("r+b") as target:
        while True:
            raw = patch.read(RECORD.size)
            if len(raw) != RECORD.size:
                raise SystemExit("truncated delta record")
            offset, length = RECORD.unpack(raw)
            if offset == (1 << 64) - 1:
                if length != 0 or count != expected_count or patch.read(1):
                    raise SystemExit("invalid delta terminator/count")
                break
            if length == 0 or length > chunk_size or offset < previous_end or offset + length > image_size:
                raise SystemExit("invalid or overlapping delta range")
            data = patch.read(length)
            if len(data) != length:
                raise SystemExit("truncated delta data")
            target.seek(offset)
            target.write(data)
            previous_end = offset + length
            count += 1
        target.flush()

print(f"output={output}\nbase_sha256={actual_base}\noutput_sha256={sha(output)}\nchanged_chunks={count}")
