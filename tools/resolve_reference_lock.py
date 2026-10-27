#!/usr/bin/env python3
"""Fetch only declared reference sources; this does not resolve/build format 2."""
import argparse
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
import tomllib

ROOT = Path(__file__).resolve().parents[1]
PIN = '0fc0fc1f9ddd0fbd4787738afef38667df5e0a95'
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--upstream', required=True, type=Path)
parser.add_argument('--cache', type=Path, default=ROOT / 'out/reference-source-cache')
args = parser.parse_args()
upstream = args.upstream.resolve()
actual = subprocess.check_output(['git', '-C', str(upstream), 'rev-parse', 'HEAD'], text=True).strip()
if actual != PIN:
    parser.error('Use the documented pinned UniXNU checker/fetch implementation')
sys.path.insert(0, str(upstream / 'scripts'))
from unixnu import feeds

declared = tomllib.loads((ROOT / 'feeds.toml').read_text(encoding='utf-8'))['source']
names = {entry['name'] for entry in declared if entry['kind'] == 'refer'}
if len(names) != len(declared):
    parser.error('This helper handles reference-only feeds; use normal unixnu fetch for a full build')
# Feed-only context deliberately skips the unavailable SoC/OS profile loader.
# It cannot be used as evidence of defconfig/status/tree or a kernel build.
cli = SimpleNamespace(local_module=[], local=None)
ctx = SimpleNamespace(root=upstream, device=ROOT, args=cli, board={},
                      raw_board={}, schema_version=1, soc=None, profile_roots={},
                      feeds_dir=args.cache.resolve(), lock_path=ROOT / 'unixnu.lock')
modules = feeds.resolve(ctx)
commits = feeds.fetch(ctx, modules, only=names)
expected = {entry['name']: entry['commit'] for entry in declared}
if commits != expected:
    raise RuntimeError('Fetched reference revisions do not match feeds.toml')
feeds.lock_write(ctx, commits)
data = ctx.lock_path.read_bytes()
ctx.lock_path.write_bytes(b'# REFERENCE-ONLY LOCK: not a resolved format 2 build lock.\n' + data)
print('PASS: fetched/pinned three references; SoC/OS/build remain unresolved')
