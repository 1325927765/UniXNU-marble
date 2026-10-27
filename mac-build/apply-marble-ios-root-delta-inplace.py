"""Apply an MRBDLT1 image delta to a disposable APFS clone in place.

The caller must provide the SHA-256 of the matching base image. The target is
modified only after both hashes and the complete delta structure validate.
"""
import argparse
import hashlib
from pathlib import Path
import struct

MAGIC = b"MRBDLT1\0"
HEADER = struct.Struct("<8sQQQ")
RECORD = struct.Struct("<QI")


def sha256(path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("target", type=Path, help="existing disposable clone of base image")
parser.add_argument("delta", type=Path)
parser.add_argument("--base-sha256", required=True)
parser.add_argument("--delta-sha256", required=True)
parser.add_argument("--output-sha256", help="expected patched image digest, if already known")
args = parser.parse_args()
target = args.target.resolve(strict=True)
delta = args.delta.resolve(strict=True)
if target == delta or not target.is_file() or not delta.is_file():
    raise SystemExit("target and delta must be distinct existing regular files")
if sha256(target) != args.base_sha256.lower():
    raise SystemExit("disposable clone does not match requested base SHA-256")
if sha256(delta) != args.delta_sha256.lower():
    raise SystemExit("delta SHA-256 mismatch")

with delta.open("rb") as patch:
    raw = patch.read(HEADER.size)
    if len(raw) != HEADER.size:
        raise SystemExit("truncated delta header")
    magic, image_size, chunk_size, expected_count = HEADER.unpack(raw)
    if magic != MAGIC or image_size != target.stat().st_size or not 4096 <= chunk_size <= 16 * 1024 * 1024:
        raise SystemExit("delta header does not match target")
    count = 0
    previous_end = 0
    while True:
        raw = patch.read(RECORD.size)
        if len(raw) != RECORD.size:
            raise SystemExit("truncated delta record")
        offset, length = RECORD.unpack(raw)
        if offset == (1 << 64) - 1:
            if length != 0 or count != expected_count or patch.read(1):
                raise SystemExit("invalid delta terminator or record count")
            break
        if (offset % chunk_size or not 0 < length <= chunk_size or
                offset < previous_end or offset + length > image_size or
                len(patch.read(length)) != length):
            raise SystemExit("invalid or truncated delta record")
        previous_end = offset + length
        count += 1

with target.open("r+b") as output, delta.open("rb") as patch:
    patch.seek(HEADER.size)
    for _ in range(expected_count):
        offset, length = RECORD.unpack(patch.read(RECORD.size))
        output.seek(offset)
        output.write(patch.read(length))
    output.flush()
actual = sha256(target)
if args.output_sha256 and actual != args.output_sha256.lower():
    raise SystemExit(f"patched clone hash mismatch: {actual}")
print(f"patched={target}\nchanged_chunks={expected_count}\nsha256={actual}")
