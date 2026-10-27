#!/usr/bin/env python3
"""Dry-run by default; hash-guarded Stage 3 Marble touch probe updater."""
from __future__ import annotations

import argparse
import datetime
import hashlib
import os
from pathlib import Path
import shutil
import sys
import tempfile

EXPECTED_STAGE2_SHA256 = "9bae03bd65080e3d27f1c23997960149aee68dd33e05f6221a1f50c393af7cb4"
PROBE_REL = Path("iokit/Kernel/arm/MarbleTouchProbe.cpp")
FILES_REL = Path("iokit/conf/files.arm64")
CLOCK_ENTRY_PATH = "iokit/Kernel/arm/MarbleTouchProbeClock.c"
NEW_HELPERS = (
    "MarbleTouchPrereq.cpp",
    "MarbleTouchPrereq.h",
    "MarbleTouchPrereqLayout.h",
    "marble_smmu_stream.c",
    "marble_smmu_stream.h",
)
NEW_BUILD_ENTRIES = (
    "iokit/Kernel/arm/MarbleTouchPrereq.cpp",
    "iokit/Kernel/arm/marble_smmu_stream.c",
)


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


def atomic_create(path: Path, data: bytes, mode: int) -> None:
    """Install a complete file atomically without replacing a racing target."""
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temp_name, mode)
        os.link(temp_name, path)
    finally:
        try:
            os.unlink(temp_name)
        except OSError:
            pass


def _entry_indices(lines: list[str], path: str) -> list[int]:
    found = []
    for index, line in enumerate(lines):
        fields = line.split("#", 1)[0].split()
        if fields and fields[0] == path:
            if len(fields) < 3 or fields[-2:] != ["optional", "iokitcpp"]:
                raise ValueError(f"build entry for {path} does not use optional iokitcpp")
            found.append(index)
    return found


def insert_build_entries(text: str) -> str:
    lines = text.splitlines(keepends=True)
    probes = _entry_indices(lines, str(PROBE_REL).replace("\\", "/"))
    clocks = _entry_indices(lines, CLOCK_ENTRY_PATH)
    if len(probes) != 1:
        raise ValueError(f"expected exactly one probe iokitcpp entry; found {len(probes)}")
    if len(clocks) != 1 or clocks[0] <= probes[0]:
        raise ValueError("expected exactly one existing clock helper entry after probe entry")
    for entry in NEW_BUILD_ENTRIES:
        if _entry_indices(lines, entry):
            raise ValueError(f"build entry already present: {entry}")
    newline = "\r\n" if "\r\n" in text else "\n"
    insert_at = clocks[0] + 1
    lines[insert_at:insert_at] = [entry + " optional iokitcpp" + newline for entry in NEW_BUILD_ENTRIES]
    return "".join(lines)


def validate_sources(source_dir: Path) -> dict[str, bytes]:
    sources = {name: (source_dir / name).read_bytes() for name in
               ("MarbleTouchProbe.cpp", *NEW_HELPERS)}
    text = {name: data.decode("utf-8") for name, data in sources.items()}
    probe = text["MarbleTouchProbe.cpp"]
    for marker in ("class MarbleTouchProbe", "MarbleTouchProbe::start",
                   "marble_spi_clock_probe", "marble_touch_prereq_snapshot",
                   "MARBLE TOUCH PREREQ", "mode3"):
        if marker not in probe:
            raise ValueError(f"staged probe lacks required Stage 3 marker/function: {marker}")
    prereq = text["MarbleTouchPrereq.cpp"]
    if "marble_touch_prereq_snapshot" not in prereq or "captureSmmuSnapshot" not in prereq:
        raise ValueError("MarbleTouchPrereq.cpp lacks snapshot entry or SMMU capture")
    if "marble_touch_prereq_snapshot" not in text["MarbleTouchPrereq.h"]:
        raise ValueError("MarbleTouchPrereq.h lacks snapshot declaration")
    layout = text["MarbleTouchPrereqLayout.h"]
    for marker in ("MARBLE_TOUCH_PREREQ_GPI_BASE", "MARBLE_TOUCH_PREREQ_TLMM_BASE",
                   "MARBLE_TOUCH_PREREQ_GPI_TX0_CONTEXT"):
        if marker not in layout:
            raise ValueError(f"MarbleTouchPrereqLayout.h lacks required layout marker: {marker}")
    if "marble_smmu_decode_stream" not in text["marble_smmu_stream.c"]:
        raise ValueError("marble_smmu_stream.c lacks decoder implementation")
    if "marble_smmu_decode_stream" not in text["marble_smmu_stream.h"]:
        raise ValueError("marble_smmu_stream.h lacks decoder declaration")
    return sources


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--xnu-root", required=True, type=Path,
                        help="legacy XNU checkout root; no Mac or device is contacted")
    parser.add_argument("--expected-old-sha256", required=True,
                        help="exact SHA-256 of the installed Stage 2 MarbleTouchProbe.cpp")
    parser.add_argument("--source-dir", type=Path,
                        help="staged touch source directory; defaults to repository touch/")
    parser.add_argument("--apply", action="store_true",
                        help="write Stage 3 source/build entries; default is dry-run")
    args = parser.parse_args(argv)

    expected = args.expected_old_sha256.lower()
    if len(expected) != 64 or any(c not in "0123456789abcdef" for c in expected):
        print("error: --expected-old-sha256 must be exactly 64 hex digits", file=sys.stderr)
        return 2
    if expected != EXPECTED_STAGE2_SHA256:
        print("error: expected hash does not match the reviewed Stage 2 hash", file=sys.stderr)
        return 2

    root = args.xnu_root.resolve()
    source_dir = (args.source_dir or Path(__file__).resolve().parents[1] / "touch").resolve()
    probe_target = root / PROBE_REL
    files_target = root / FILES_REL
    helper_targets = {name: root / "iokit" / "Kernel" / "arm" / name for name in NEW_HELPERS}
    for path in (probe_target, files_target):
        if not path.is_file():
            print(f"error: required installed file missing: {path}", file=sys.stderr)
            return 2
    for path in helper_targets.values():
        if path.exists():
            print(f"error: refusing to overwrite existing helper: {path}", file=sys.stderr)
            return 2

    old_probe = probe_target.read_bytes()
    actual_hash = hashlib.sha256(old_probe).hexdigest()
    if actual_hash != expected:
        print(f"error: installed source hash is {actual_hash}; expected {expected}; no files changed",
              file=sys.stderr)
        return 2
    try:
        new_sources = validate_sources(source_dir)
        new_files = insert_build_entries(files_target.read_bytes().decode("utf-8"))
    except (OSError, UnicodeDecodeError, ValueError) as error:
        print(f"error: {error}; no files changed", file=sys.stderr)
        return 2

    print(f"XNU root: {root}")
    print(f"Installed Stage 2 SHA-256 verified: {actual_hash}")
    print(f"Replace only: {probe_target}")
    for name, target in helper_targets.items():
        print(f"Add new helper: {target} ({len(new_sources[name])} bytes)")
    print(f"Add two unique optional iokitcpp entries after existing {CLOCK_ENTRY_PATH}")
    if not args.apply:
        print("Dry run only. Re-run with --apply; existing files are backed up first.")
        return 0

    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    existing = (probe_target, files_target)
    backups = [(path, path.with_name(path.name + f".bak.marble-touch-probe-stage3.{stamp}"))
               for path in existing]
    if any(backup.exists() for _, backup in backups):
        print("error: backup path already exists; no files changed", file=sys.stderr)
        return 2
    originals = {path: path.read_bytes() for path in existing}
    modes = {path: path.stat().st_mode & 0o7777 for path in existing}
    source_modes = {name: (source_dir / name).stat().st_mode & 0o7777
                    for name in NEW_HELPERS}
    created: list[Path] = []
    try:
        for path, backup in backups:
            shutil.copy2(path, backup)
        atomic_write(probe_target, new_sources["MarbleTouchProbe.cpp"], modes[probe_target])
        atomic_write(files_target, new_files.encode("utf-8"), modes[files_target])
        for name in NEW_HELPERS:
            target = helper_targets[name]
            atomic_create(target, new_sources[name], source_modes[name])
            created.append(target)
    except Exception as error:
        print(f"error while applying: {error}", file=sys.stderr)
        rollback_errors = []
        for path, data in originals.items():
            try:
                atomic_write(path, data, modes[path])
            except Exception as rollback_error:
                rollback_errors.append(f"{path}: {rollback_error}")
        for path in reversed(created):
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
