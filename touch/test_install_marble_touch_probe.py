#!/usr/bin/env python3
"""Focused fixture checks for probe installer structure and failure rollback."""
from __future__ import annotations

import contextlib
import importlib.util
import io
from pathlib import Path
import tempfile


SCRIPT = Path(__file__).with_name("install_marble_touch_probe.py")
SPEC = importlib.util.spec_from_file_location("touch_probe_installer", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
INSTALLER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(INSTALLER)


def make_fixture(root: Path) -> tuple[Path, Path]:
    files_path = root / "iokit" / "conf" / "files.arm64"
    tables_path = root / "iokit" / "KernelConfigTables.cpp"
    (root / "iokit" / "Kernel" / "arm").mkdir(parents=True)
    files_path.parent.mkdir(parents=True)
    files_path.write_text(
        "iokit/Kernel/arm/AppleARMSMP.cpp\toptional iokitcpp\n"
        "# other source\n", encoding="utf-8")
    tables_path.write_text(
        'const char * gIOKernelConfigTables =\n'
        '    "("\n'
        '    "   {"\n'
        '    "     \'IOClass\'         = IOPanicPlatform;"\n'
        '    "   }"\n'
        '    ")";\n', encoding="utf-8")
    return files_path, tables_path


def run_installer(root: Path) -> int:
    old_argv = INSTALLER.sys.argv
    INSTALLER.sys.argv = [str(SCRIPT), "--xnu-root", str(root), "--apply"]
    try:
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return INSTALLER.main()
    finally:
        INSTALLER.sys.argv = old_argv


def structural_apply_check(root: Path) -> None:
    files_path, tables_path = make_fixture(root)
    assert run_installer(root) == 0
    tables = tables_path.read_text(encoding="utf-8")
    start = tables.index("#if defined(ARM64_BOARD_CONFIG_MARBLE)")
    end = tables.index("#endif", start)
    panic_open = tables.index('    "   {"', end)
    panic_class = tables.index("IOPanicPlatform", panic_open)
    assert start < end < panic_open < panic_class
    inserted = tables[start:end]
    assert "'IOClass'         = MarbleTouchProbe;" in inserted
    assert "'IOProviderClass' = IOResources;" in inserted
    assert "'IOMatchCategory' = MarbleTouchProbe;" in inserted
    assert inserted.count('"   {"') == 1 and inserted.count('"   },"') == 1
    assert tables.count("IOPanicPlatform") == 1
    assert "MarbleTouchProbe.cpp" in files_path.read_text(encoding="utf-8")
    assert (root / "iokit" / "Kernel" / "arm" / "MarbleTouchProbe.cpp").is_file()


def failure_rollback_check(root: Path) -> None:
    files_path, tables_path = make_fixture(root)
    original_files = files_path.read_bytes()
    original_tables = tables_path.read_bytes()
    old_modes = (files_path.stat().st_mode & 0o7777, tables_path.stat().st_mode & 0o7777)
    real_atomic_write = INSTALLER.atomic_write
    calls = 0

    def fail_once(path: Path, data: bytes, mode: int) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("fixture write failure")
        real_atomic_write(path, data, mode)

    INSTALLER.atomic_write = fail_once
    try:
        assert run_installer(root) == 1
    finally:
        INSTALLER.atomic_write = real_atomic_write

    assert files_path.read_bytes() == original_files
    assert tables_path.read_bytes() == original_tables
    assert (files_path.stat().st_mode & 0o7777, tables_path.stat().st_mode & 0o7777) == old_modes
    assert not (root / "iokit" / "Kernel" / "arm" / "MarbleTouchProbe.cpp").exists()
    assert list(root.rglob("*.bak.marble-touch-probe.*")), "pre-write backups should be retained"


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="marble-touch-probe-test-") as temp:
        structural_apply_check(Path(temp) / "structure")
        failure_rollback_check(Path(temp) / "rollback")
    print("Marble touch probe installer fixture checks: PASS")


if __name__ == "__main__":
    main()
