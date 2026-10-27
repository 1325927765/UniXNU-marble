#!/usr/bin/env python3
"""Host fixture for the guarded Stage 3 Marble touch probe updater."""
from __future__ import annotations

import contextlib
import importlib.util
import io
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
STAGE2_PROBE = REPO / "research" / "touch-clock-stage2-20261025" / "touch" / "MarbleTouchProbe.cpp"
SOURCE_DIR = REPO / "touch"
UPDATER_PATH = HERE / "update-marble-touch-probe-stage3.py"
spec = importlib.util.spec_from_file_location("touch_stage3_updater", UPDATER_PATH)
updater = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(updater)


def make_tree(root: Path) -> tuple[Path, Path]:
    probe = root / updater.PROBE_REL
    files = root / updater.FILES_REL
    probe.parent.mkdir(parents=True)
    files.parent.mkdir(parents=True)
    shutil.copyfile(STAGE2_PROBE, probe)
    files.write_text(
        "iokit/Kernel/arm/MarbleTouchProbe.cpp optional iokitcpp\n"
        "iokit/Kernel/arm/MarbleTouchProbeClock.c                         optional iokitcpp\n"
        "iokit/Kernel/arm/Unrelated.cpp optional iokitcpp\n",
        encoding="utf-8")
    return probe, files


def call(root: Path, *extra: str) -> tuple[int, str, str]:
    args = ["--xnu-root", str(root), "--expected-old-sha256",
            updater.EXPECTED_STAGE2_SHA256, "--source-dir", str(SOURCE_DIR), *extra]
    stdout, stderr = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        result = updater.main(args)
    return result, stdout.getvalue(), stderr.getvalue()


class Stage3UpdaterFixture(unittest.TestCase):
    def test_wrong_hash_refuses_without_changes(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            probe, files = make_tree(root)
            before = (probe.read_bytes(), files.read_bytes())
            result, _, error = call(root, "--expected-old-sha256", "0" * 64)
            self.assertEqual(result, 2)
            self.assertIn("reviewed Stage 2 hash", error)
            self.assertEqual((probe.read_bytes(), files.read_bytes()), before)
            self.assertFalse((probe.parent / "MarbleTouchPrereq.cpp").exists())

    def test_installed_probe_hash_mismatch_refuses_without_changes(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            probe, files = make_tree(root)
            probe.write_bytes(probe.read_bytes() + b"\\n/* local drift */\\n")
            before = (probe.read_bytes(), files.read_bytes())
            result, _, error = call(root)
            self.assertEqual(result, 2)
            self.assertIn("no files changed", error)
            self.assertEqual((probe.read_bytes(), files.read_bytes()), before)
            self.assertFalse((probe.parent / "MarbleTouchPrereq.cpp").exists())

    def test_default_is_dry_run(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            probe, files = make_tree(root)
            before = (probe.read_bytes(), files.read_bytes())
            result, output, _ = call(root)
            self.assertEqual(result, 0)
            self.assertIn("Dry run only", output)
            self.assertEqual((probe.read_bytes(), files.read_bytes()), before)
            self.assertFalse((probe.parent / "MarbleTouchPrereq.cpp").exists())

    def test_any_existing_new_file_refuses_before_writing(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            probe, files = make_tree(root)
            preexisting = probe.parent / "marble_smmu_stream.h"
            preexisting.write_text("keep me", encoding="utf-8")
            before = (probe.read_bytes(), files.read_bytes())
            result, _, error = call(root, "--apply")
            self.assertEqual(result, 2)
            self.assertIn("refusing to overwrite existing helper", error)
            self.assertEqual((probe.read_bytes(), files.read_bytes()), before)
            self.assertEqual(preexisting.read_text(encoding="utf-8"), "keep me")

    def test_success_replaces_probe_adds_five_helpers_and_two_entries(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            probe, files = make_tree(root)
            original_modes = (probe.stat().st_mode & 0o7777,
                              files.stat().st_mode & 0o7777)
            result, _, error = call(root, "--apply")
            self.assertEqual(result, 0, error)
            self.assertEqual(probe.read_bytes(), (SOURCE_DIR / "MarbleTouchProbe.cpp").read_bytes())
            self.assertEqual((probe.stat().st_mode & 0o7777,
                              files.stat().st_mode & 0o7777), original_modes)
            for name in updater.NEW_HELPERS:
                self.assertEqual((probe.parent / name).read_bytes(), (SOURCE_DIR / name).read_bytes())
            content = files.read_text(encoding="utf-8")
            lines = content.splitlines()
            probe_i = lines.index("iokit/Kernel/arm/MarbleTouchProbe.cpp optional iokitcpp")
            clock_i = next(i for i, line in enumerate(lines)
                           if line.startswith(updater.CLOCK_ENTRY_PATH))
            prereq_i = next(i for i, line in enumerate(lines)
                            if line.startswith("iokit/Kernel/arm/MarbleTouchPrereq.cpp"))
            decoder_i = next(i for i, line in enumerate(lines)
                             if line.startswith("iokit/Kernel/arm/marble_smmu_stream.c"))
            self.assertEqual(clock_i, probe_i + 1)
            self.assertEqual([prereq_i, decoder_i], [clock_i + 1, clock_i + 2])
            for index in (prereq_i, decoder_i):
                self.assertTrue(lines[index].endswith(" optional iokitcpp"))
            self.assertEqual(sum(updater.CLOCK_ENTRY_PATH in line for line in lines), 1)
            backups = list(root.rglob("*.bak.marble-touch-probe-stage3.*"))
            self.assertEqual(len(backups), 2)

    def test_injected_helper_write_failure_rolls_back_and_keeps_backups(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            probe, files = make_tree(root)
            originals = (probe.read_bytes(), files.read_bytes())
            real_create = updater.atomic_create

            def fail_second_helper(path, data, mode):
                if path.name == "MarbleTouchPrereq.h":
                    raise OSError("injected fixture write failure")
                return real_create(path, data, mode)

            with patch.object(updater, "atomic_create", side_effect=fail_second_helper):
                result, _, error = call(root, "--apply")
            self.assertEqual(result, 1)
            self.assertIn("injected fixture write failure", error)
            self.assertEqual((probe.read_bytes(), files.read_bytes()), originals)
            for name in updater.NEW_HELPERS:
                self.assertFalse((probe.parent / name).exists())
            self.assertEqual(len(list(root.rglob("*.bak.marble-touch-probe-stage3.*"))), 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
