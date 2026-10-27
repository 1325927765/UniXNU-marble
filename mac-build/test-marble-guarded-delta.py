"""Mock-ADB safety tests for apply-marble-guarded-delta.py.

Uses a sparse 16 GiB host file as userdata. Never opens a real ADB connection.
Run with: python3 mac-build/test-marble-guarded-delta.py
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / 'mac-build' / 'apply-marble-guarded-delta.py'
MIB = 1024 * 1024
VOLUME = 16 * 1024**3
OFFSETS = (MIB, 2 * MIB)


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class GuardedDeltaTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='marble-delta-test-')
        self.base = Path(self.temp.name)
        self.delta = self.base / 'delta'
        self.delta.mkdir()
        self.device = self.base / 'userdata.img'
        with self.device.open('wb') as f:
            f.truncate(VOLUME)
        with self.device.open('r+b') as f:
            f.seek(1024)
            f.write(b'H+')
        self.before = [b'A' * MIB, b'C' * MIB]
        self.after = [b'B' * MIB, b'D' * MIB]
        self.records = []
        for index, offset in enumerate(OFFSETS):
            before_name = f'before-{index}.bin'
            after_name = f'after-{index}.bin'
            (self.delta / before_name).write_bytes(self.before[index])
            (self.delta / after_name).write_bytes(self.after[index])
            self.records.append(dict(offset=offset, length=MIB,
                before_file=before_name, after_file=after_name,
                before_sha256=sha(self.before[index]),
                after_sha256=sha(self.after[index])))
        manifest = dict(format='marble-guarded-blocks-v1', volume_bytes=VOLUME,
            changed_bytes=2 * MIB, records=self.records)
        (self.delta / 'manifest.json').write_text(json.dumps(manifest))
        self.manifest_sha = sha((self.delta / 'manifest.json').read_bytes())
        self.adb_script = self.base / 'fake-adb.py'
        self.adb_script.write_text(self.fake_adb_source())
        self.adb_script.chmod(0o755)
        self.seed(['before', 'before'])

    def tearDown(self):
        self.temp.cleanup()

    def fake_adb_source(self):
        # The script receives the same argv shape as `adb -s SERIAL ...`.
        return '''#!/usr/bin/env python3
import os, re, shutil, sys
from pathlib import Path
base = Path(os.environ["MARBLE_FAKE_ADB_ROOT"])
device = base / "userdata.img"
args = sys.argv[1:]
assert args[:2] == ["-s", "MOCK-SERIAL"], args
args = args[2:]
if args[0] == "shell":
    cmd = " ".join(args[1:])
    if cmd == "getprop ro.product.device": print("marble")
    elif cmd == "readlink -f /dev/block/by-name/userdata": print("/dev/block/sda")
    elif cmd == "cat /proc/mounts": print("rootfs / rootfs rw 0 0")
    elif cmd.startswith("mktemp -d "):
        path = "/tmp/marble-setup-blocks.MOCK"
        (base / "remote").mkdir(exist_ok=True)
        print(path)
    elif cmd.startswith("dd if="):
        match = re.fullmatch(r"dd if=(/tmp/marble-setup-blocks\\.MOCK/[^ ]+) of=/dev/block/by-name/userdata bs=4096 seek=(\\d+) count=(\\d+) conv=notrunc,fsync", cmd)
        assert match, cmd
        src = base / "remote" / Path(match.group(1)).name
        with src.open("rb") as f: data = f.read()
        assert len(data) == int(match.group(3)) * 4096
        with device.open("r+b") as f:
            f.seek(int(match.group(2)) * 4096); f.write(data); f.flush(); os.fsync(f.fileno())
    elif cmd.startswith("rm -f /tmp/marble-setup-blocks.MOCK/"):
        (base / "remote" / cmd.rsplit("/", 1)[1]).unlink(missing_ok=True)
    elif cmd == "rmdir /tmp/marble-setup-blocks.MOCK":
        (base / "remote").rmdir()
    else: raise AssertionError("unexpected shell: " + cmd)
elif args[0] == "exec-out":
    cmd = " ".join(args[1:])
    match = re.search(r"count=(\\d+) skip=(\\d+)", cmd)
    assert match, cmd
    length, offset = map(int, match.groups())
    with device.open("rb") as f: f.seek(offset); sys.stdout.buffer.write(f.read(length))
elif args[0] == "push":
    source, target = Path(args[1]), args[2]
    assert target.startswith("/tmp/marble-setup-blocks.MOCK/")
    dest = base / "remote" / Path(target).name
    dest.parent.mkdir(exist_ok=True)
    shutil.copyfile(source, dest)
else: raise AssertionError("unexpected adb args: " + repr(args))
'''

    def run_tool(self, *args):
        env = os.environ.copy()
        env['MARBLE_FAKE_ADB_ROOT'] = str(self.base)
        return subprocess.run([os.fspath(__import__('sys').executable), os.fspath(TARGET),
            os.fspath(self.delta), '--adb', os.fspath(self.adb_script),
            '--serial', 'MOCK-SERIAL', *args], capture_output=True, text=True, env=env)

    def seed(self, states):
        with self.device.open('r+b') as f:
            for index, state in enumerate(states):
                f.seek(OFFSETS[index])
                f.write((self.before if state == 'before' else self.after)[index])

    def read_record(self, index):
        with self.device.open('rb') as f:
            f.seek(OFFSETS[index]); return f.read(MIB)

    def assert_success(self, result):
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_dry_run_reads_only(self):
        prior = [self.read_record(i) for i in range(2)]
        self.assert_success(self.run_tool())
        self.assertEqual(prior, [self.read_record(i) for i in range(2)])
        self.assertFalse((self.delta / 'device-apply-progress.json').exists())

    def test_interrupted_mixed_state_resumes_apply(self):
        self.seed(['after', 'before'])
        self.assert_success(self.run_tool('--apply'))
        self.assertEqual([self.read_record(i) for i in range(2)], self.after)

    def test_rollback_and_idempotent_rollback(self):
        self.seed(['after', 'after'])
        self.assert_success(self.run_tool('--rollback', '--apply'))
        self.assertEqual([self.read_record(i) for i in range(2)], self.before)
        self.assert_success(self.run_tool('--rollback', '--apply'))
        self.assertEqual([self.read_record(i) for i in range(2)], self.before)

    def test_unknown_hash_rejected_before_any_write(self):
        with self.device.open('r+b') as f:
            f.seek(OFFSETS[0]); f.write(b'X' * MIB)
        self.seed(['before', 'before'])
        with self.device.open('r+b') as f:
            f.seek(OFFSETS[0]); f.write(b'X' * MIB)
        result = self.run_tool('--apply')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('unknown preimage', result.stderr)
        self.assertEqual(self.read_record(1), self.before[1])

    def test_logged_unknown_repair_rolls_back(self):
        with self.device.open('r+b') as f:
            f.seek(OFFSETS[0]); f.write(b'X' * MIB)
        self.seed(['before', 'after'])
        with self.device.open('r+b') as f:
            f.seek(OFFSETS[0]); f.write(b'X' * MIB)
        (self.delta / 'device-apply-progress.json').write_text(json.dumps(dict(
            manifest_sha256=self.manifest_sha, direction='before->after',
            verified_offsets=[], pending_offset=OFFSETS[0])))
        self.assert_success(self.run_tool('--rollback', '--repair-interrupted', '--apply'))
        self.assertEqual([self.read_record(i) for i in range(2)], self.before)


if __name__ == '__main__':
    unittest.main(verbosity=2)
