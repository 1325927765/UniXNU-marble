#!/usr/bin/env python3
"""Dry-run by default; opt-in installer for the Marble read-only probe."""
from __future__ import annotations

import argparse
import datetime as _datetime
import os
from pathlib import Path
import shutil
import sys
import tempfile


FILES_MARKER = "iokit/Kernel/arm/AppleARMSMP.cpp"
TABLE_MARKER = [
    '    "   {"',
    '    "     \'IOClass\'         = IOPanicPlatform;"',
]
FILES_ENTRY = "iokit/Kernel/arm/MarbleTouchProbe.cpp                         optional iokitcpp"
TABLE_ENTRY = [
    "#if defined(ARM64_BOARD_CONFIG_MARBLE)",
    '    "   {"',
    '    "     \'IOClass\'         = MarbleTouchProbe;"',
    '    "     \'IOProviderClass\' = IOResources;"',
    '    "     \'IOMatchCategory\' = MarbleTouchProbe;"',
    '    "   },"',
    "#endif",
]


def insert_after_line(text: str, marker, new_lines: list[str]) -> str:
    lines = text.splitlines(keepends=True)
    if isinstance(marker, str):
        matches = [i for i, line in enumerate(lines) if marker in line.rstrip("\r\n")]
        insertion = matches[0] + 1 if len(matches) == 1 else None
        marker_name = repr(marker)
    else:
        matches = [i for i in range(len(lines) - len(marker) + 1)
                   if [line.rstrip("\r\n") for line in lines[i:i + len(marker)]] == marker]
        insertion = matches[0] if len(matches) == 1 else None
        marker_name = repr("\\n".join(marker))
    if len(matches) != 1:
        raise ValueError(f"expected exactly one marker {marker_name}; found {len(matches)}")
    newline = "\r\n" if "\r\n" in text else "\n"
    addition = [line + newline for line in new_lines]
    lines[insertion:insertion] = addition
    return "".join(lines)


def atomic_write(path: Path, data: bytes, mode: int) -> None:
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(tmp_name, mode)
        os.replace(tmp_name, path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--xnu-root", required=True, type=Path,
                        help="legacy XNU checkout root; no Mac or device is contacted")
    parser.add_argument("--apply", action="store_true",
                        help="write the source and installer markers; default is dry-run")
    args = parser.parse_args()

    root = args.xnu_root.resolve()
    files_path = root / "iokit" / "conf" / "files.arm64"
    tables_path = root / "iokit" / "KernelConfigTables.cpp"
    source_path = Path(__file__).with_name("MarbleTouchProbe.cpp")
    dest_path = root / "iokit" / "Kernel" / "arm" / "MarbleTouchProbe.cpp"

    for path in (files_path, tables_path, source_path):
        if not path.is_file():
            print(f"error: required file missing: {path}", file=sys.stderr)
            return 2
    if not dest_path.parent.is_dir():
        print(f"error: expected legacy XNU directory missing: {dest_path.parent}", file=sys.stderr)
        return 2
    if dest_path.exists():
        print(f"error: refusing to overwrite existing source: {dest_path}", file=sys.stderr)
        return 2

    files_text = files_path.read_bytes().decode("utf-8")
    tables_text = tables_path.read_bytes().decode("utf-8")
    if FILES_ENTRY in files_text or "MarbleTouchProbe" in tables_text:
        print("error: MarbleTouchProbe appears partly or fully installed; refusing to overwrite", file=sys.stderr)
        return 2

    try:
        new_files = insert_after_line(files_text, FILES_MARKER, [FILES_ENTRY])
        new_tables = insert_after_line(tables_text, TABLE_MARKER, TABLE_ENTRY)
    except ValueError as error:
        print(f"error: {error}; no files changed", file=sys.stderr)
        return 2

    print(f"XNU root: {root}")
    print(f"Copy: {source_path} -> {dest_path}")
    print(f"Insert build entry after {FILES_MARKER!r} in {files_path}")
    print(f"Insert complete IOResources personality before the IOPanic dictionary in {tables_path}")
    print("Safety: service does nothing unless boot arg marbletouchprobe=1; it only maps read-only GCC/GENI state.")
    if not args.apply:
        print("Dry run only. Re-run with --apply to write; originals are backed up first.")
        return 0

    stamp = _datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    targets = ((files_path, new_files.encode("utf-8")),
               (tables_path, new_tables.encode("utf-8")))
    originals = {path: path.read_bytes() for path, _ in targets}
    modes = {path: path.stat().st_mode & 0o7777 for path, _ in targets}
    backups = []
    for path, _ in targets:
        backup = path.with_name(path.name + f".bak.marble-touch-probe.{stamp}")
        if backup.exists():
            print(f"error: backup already exists: {backup}; no files changed", file=sys.stderr)
            return 2
        backups.append((path, backup))

    try:
        for path, backup in backups:
            shutil.copy2(path, backup)
        atomic_write(dest_path, source_path.read_bytes(), source_path.stat().st_mode & 0o7777)
        for path, data in targets:
            atomic_write(path, data, modes[path])
    except Exception as error:
        print(f"error while applying: {error}", file=sys.stderr)
        rollback_errors = []
        for path, data in originals.items():
            try:
                atomic_write(path, data, modes[path])
            except Exception as rollback_error:
                rollback_errors.append(f"{path}: {rollback_error}")
        if dest_path.exists():
            try:
                dest_path.unlink()
            except OSError as rollback_error:
                rollback_errors.append(f"{dest_path}: {rollback_error}")
        print("Rollback attempted; backups are retained:", file=sys.stderr)
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
