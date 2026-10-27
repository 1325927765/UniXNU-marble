#!/usr/bin/env python3
"""Temporary-tree structural, hash-guard, and rollback checks for Stage 2 updater."""
from __future__ import annotations

import contextlib
import hashlib
import importlib.util
import io
from pathlib import Path
import tempfile


SCRIPT = Path(__file__).parents[1] / "mac-build" / "update-marble-touch-probe-stage2.py"
SPEC = importlib.util.spec_from_file_location("stage2_updater", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
UPDATER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(UPDATER)


def fixture(root: Path) -> tuple[Path, Path, bytes, bytes]:
    probe = root / "iokit" / "Kernel" / "arm" / "MarbleTouchProbe.cpp"
    files = root / "iokit" / "conf" / "files.arm64"
    probe.parent.mkdir(parents=True)
    files.parent.mkdir(parents=True)
    old_probe = b"stage one probe with user-preserved source\n"
    old_files = (b"iokit/Kernel/arm/AppleARMSMP.cpp optional iokitcpp\n"
                 b"iokit/Kernel/arm/MarbleTouchProbe.cpp optional iokitcpp\n")
    probe.write_bytes(old_probe)
    files.write_bytes(old_files)
    return probe, files, old_probe, old_files


def run(root: Path, old_probe: bytes, apply: bool) -> int:
    argv = [str(SCRIPT), "--xnu-root", str(root), "--expected-old-sha256",
            hashlib.sha256(old_probe).hexdigest()]
    if apply:
        argv.append("--apply")
    original = UPDATER.sys.argv
    UPDATER.sys.argv = argv
    try:
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return UPDATER.main()
    finally:
        UPDATER.sys.argv = original


def successful_apply(root: Path) -> None:
    probe, files, old_probe, old_files = fixture(root)
    assert run(root, old_probe, apply=False) == 0
    assert probe.read_bytes() == old_probe and files.read_bytes() == old_files
    assert run(root, old_probe, apply=True) == 0
    assert probe.read_bytes() == (Path(__file__).with_name("MarbleTouchProbe.cpp").read_bytes())
    assert (root / "iokit" / "Kernel" / "arm" / "MarbleTouchProbeClock.c").is_file()
    assert (root / "iokit" / "Kernel" / "arm" / "MarbleTouchProbeClock.h").is_file()
    assert UPDATER.BUILD_ENTRY.encode() in files.read_bytes()
    backups = list(root.rglob("*.bak.marble-touch-probe-stage2.*"))
    assert len(backups) == 2
    assert any(path.read_bytes() == old_probe for path in backups)
    assert any(path.read_bytes() == old_files for path in backups)


def failed_apply_rolls_back(root: Path) -> None:
    probe, files, old_probe, old_files = fixture(root)
    real_write = UPDATER.atomic_write
    calls = 0

    def fail_once(path: Path, data: bytes, mode: int) -> None:
        nonlocal calls
        calls += 1
        if calls == 3:
            raise OSError("fixture helper write failure")
        real_write(path, data, mode)

    UPDATER.atomic_write = fail_once
    try:
        assert run(root, old_probe, apply=True) == 1
    finally:
        UPDATER.atomic_write = real_write
    assert probe.read_bytes() == old_probe and files.read_bytes() == old_files
    assert not (root / "iokit" / "Kernel" / "arm" / "MarbleTouchProbeClock.c").exists()
    assert not (root / "iokit" / "Kernel" / "arm" / "MarbleTouchProbeClock.h").exists()
    assert len(list(root.rglob("*.bak.marble-touch-probe-stage2.*"))) == 2


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="marble-touch-stage2-update-") as temp:
        successful_apply(Path(temp) / "success")
        failed_apply_rolls_back(Path(temp) / "rollback")
    print("Marble Stage 2 updater fixture checks: PASS")


if __name__ == "__main__":
    main()
