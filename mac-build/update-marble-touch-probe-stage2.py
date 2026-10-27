#!/usr/bin/env python3
"""Dry-run by default; hash-guarded, backup-first Stage 2 probe updater."""
from __future__ import annotations

import argparse
import datetime as _datetime
import hashlib
import os
from pathlib import Path
import shutil
import sys
import tempfile


BUILD_MARKER = "iokit/Kernel/arm/MarbleTouchProbe.cpp"
BUILD_ENTRY = "iokit/Kernel/arm/MarbleTouchProbeClock.c                         optional iokitcpp"


def atomic_write(path: Path, data: bytes, mode: int) -> None:
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temp_name, mode)
        os.replace(temp_name, path)
    except Exception:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise


def insert_helper_build_entry(text: str) -> str:
    lines = text.splitlines(keepends=True)
    matches = [i for i, line in enumerate(lines)
               if BUILD_MARKER in line.rstrip("\r\n")]
    if len(matches) != 1:
        raise ValueError(f"expected one existing probe build entry; found {len(matches)}")
    if BUILD_ENTRY in text:
        raise ValueError("clock helper build entry is already present")
    newline = "\r\n" if "\r\n" in text else "\n"
    lines.insert(matches[0] + 1, BUILD_ENTRY + newline)
    return "".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--xnu-root", required=True, type=Path,
                        help="legacy XNU checkout root; no Mac or device is contacted")
    parser.add_argument("--expected-old-sha256", required=True,
                        help="exact SHA-256 of the installed Stage 1 MarbleTouchProbe.cpp")
    parser.add_argument("--apply", action="store_true",
                        help="write Stage 2 source/build entry; default is dry-run")
    args = parser.parse_args()

    expected = args.expected_old_sha256.lower()
    if len(expected) != 64 or any(c not in "0123456789abcdef" for c in expected):
        print("error: --expected-old-sha256 must be exactly 64 hex digits", file=sys.stderr)
        return 2

    root = args.xnu_root.resolve()
    probe_target = root / "iokit" / "Kernel" / "arm" / "MarbleTouchProbe.cpp"
    files_target = root / "iokit" / "conf" / "files.arm64"
    helper_c_target = root / "iokit" / "Kernel" / "arm" / "MarbleTouchProbeClock.c"
    helper_h_target = root / "iokit" / "Kernel" / "arm" / "MarbleTouchProbeClock.h"
    source_root = Path(__file__).resolve().parents[1] / "touch"
    probe_source = source_root / "MarbleTouchProbe.cpp"
    helper_c_source = source_root / "MarbleTouchProbeClock.c"
    helper_h_source = source_root / "MarbleTouchProbeClock.h"

    required = (probe_target, files_target, probe_source, helper_c_source, helper_h_source)
    for path in required:
        if not path.is_file():
            print(f"error: required file missing: {path}", file=sys.stderr)
            return 2
    for path in (helper_c_target, helper_h_target):
        if path.exists():
            print(f"error: refusing to overwrite existing helper: {path}", file=sys.stderr)
            return 2

    old_probe = probe_target.read_bytes()
    actual_hash = hashlib.sha256(old_probe).hexdigest()
    if actual_hash != expected:
        print(f"error: installed source hash is {actual_hash}; expected {expected}; no files changed",
              file=sys.stderr)
        return 2
    if BUILD_ENTRY in files_target.read_text(encoding="utf-8"):
        print("error: helper build entry already present; refusing partial/duplicate update", file=sys.stderr)
        return 2

    probe_bytes = probe_source.read_bytes()
    helper_c_bytes = helper_c_source.read_bytes()
    helper_h_bytes = helper_h_source.read_bytes()
    probe_text = probe_bytes.decode("utf-8")
    if "marble_spi_clock_probe" not in probe_text or "MARBLE TOUCH CLOCK:" not in probe_text:
        print("error: staged source lacks Stage 2 helper symbol or log marker", file=sys.stderr)
        return 2
    try:
        new_files = insert_helper_build_entry(files_target.read_bytes().decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as error:
        print(f"error: {error}; no files changed", file=sys.stderr)
        return 2

    print(f"XNU root: {root}")
    print(f"Installed Stage 1 SHA-256 verified: {actual_hash}")
    print(f"Replace only after exact hash match: {probe_target}")
    print(f"Add new helper: {helper_c_target} and {helper_h_target}")
    print(f"Add one helper build entry under iokitcpp after {BUILD_MARKER!r} in {files_target}")
    if not args.apply:
        print("Dry run only. Re-run with --apply to write; existing files are backed up first.")
        return 0

    stamp = _datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    existing = (probe_target, files_target)
    backups = []
    for path in existing:
        backup = path.with_name(path.name + f".bak.marble-touch-probe-stage2.{stamp}")
        if backup.exists():
            print(f"error: backup already exists: {backup}; no files changed", file=sys.stderr)
            return 2
        backups.append((path, backup))

    originals = {path: path.read_bytes() for path in existing}
    modes = {path: path.stat().st_mode & 0o7777 for path in existing}
    new_files_bytes = new_files.encode("utf-8")
    try:
        for path, backup in backups:
            shutil.copy2(path, backup)
        atomic_write(probe_target, probe_bytes, modes[probe_target])
        atomic_write(files_target, new_files_bytes, modes[files_target])
        atomic_write(helper_c_target, helper_c_bytes, helper_c_source.stat().st_mode & 0o7777)
        atomic_write(helper_h_target, helper_h_bytes, helper_h_source.stat().st_mode & 0o7777)
    except Exception as error:
        print(f"error while applying: {error}", file=sys.stderr)
        rollback_errors = []
        for path, data in originals.items():
            try:
                atomic_write(path, data, modes[path])
            except Exception as rollback_error:
                rollback_errors.append(f"{path}: {rollback_error}")
        for path in (helper_h_target, helper_c_target):
            if path.exists():
                try:
                    path.unlink()
                except OSError as rollback_error:
                    rollback_errors.append(f"{path}: {rollback_error}")
        print("Rollback attempted; backups retained:", file=sys.stderr)
        for _, backup in backups:
            print(f"  {backup}", file=sys.stderr)
        for rollback_error in rollback_errors:
            print(f"ROLLBACK ERROR: {rollback_error}", file=sys.stderr)
        return 1

    print("Applied. Backups:")
    for _, backup in backups:
        print(f"  {backup}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
