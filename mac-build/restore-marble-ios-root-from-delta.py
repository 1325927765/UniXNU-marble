#!/usr/bin/env python3
"""Restore a modified raw root image to its baseline using an MRBDLT1 delta.

The delta records contain the modified bytes. Every target record is checked
against those bytes before any write, then replaced with the baseline bytes.
This is for disposable QEMU root clones only.
"""
import argparse
from pathlib import Path
import struct

MAGIC = b"MRBDLT1\0"
HEADER = struct.Struct("<8sQQQ")
RECORD = struct.Struct("<QI")

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("base", type=Path)
parser.add_argument("modified", type=Path)
parser.add_argument("delta", type=Path)
args = parser.parse_args()
base = args.base.resolve(strict=True)
modified = args.modified.resolve(strict=True)
delta = args.delta.resolve(strict=True)
if len({base, modified, delta}) != 3:
    raise SystemExit("base, modified, and delta must be distinct")
if not all(path.is_file() for path in (base, modified, delta)):
    raise SystemExit("all inputs must be existing regular files")

with delta.open("rb") as patch:
    raw = patch.read(HEADER.size)
    if len(raw) != HEADER.size:
        raise SystemExit("truncated delta header")
    magic, size, chunk_size, expected_count = HEADER.unpack(raw)
    if (magic != MAGIC or size != base.stat().st_size or
            size != modified.stat().st_size or
            not 4096 <= chunk_size <= 16 * 1024 * 1024):
        raise SystemExit("delta header does not match the images")
    records = []
    previous_end = 0
    with modified.open("rb") as target:
        for _ in range(expected_count):
            raw = patch.read(RECORD.size)
            if len(raw) != RECORD.size:
                raise SystemExit("truncated delta record")
            offset, length = RECORD.unpack(raw)
            if (offset % chunk_size or not 0 < length <= chunk_size or
                    offset < previous_end or offset + length > size):
                raise SystemExit("invalid delta record")
            expected = patch.read(length)
            if len(expected) != length:
                raise SystemExit("truncated delta data")
            target.seek(offset)
            if target.read(length) != expected:
                raise SystemExit(f"modified image differs from delta at offset {offset}")
            records.append((offset, length))
            previous_end = offset + length
    raw = patch.read(RECORD.size)
    if len(raw) != RECORD.size or RECORD.unpack(raw) != ((1 << 64) - 1, 0) or patch.read(1):
        raise SystemExit("invalid delta terminator")

with base.open("rb") as source, modified.open("r+b") as target:
    for offset, length in records:
        source.seek(offset)
        target.seek(offset)
        target.write(source.read(length))
    target.flush()
print(f"restored={modified}\nchunks={len(records)}\nbytes={sum(length for _, length in records)}")
