#!/usr/bin/env python3
"""Use pinned legacy IIG generated source only when all source inputs match exactly."""
import hashlib
import json
from pathlib import Path
import sys
import os

root = Path(os.environ.get('MARBLE_BUILD_ROOT', str(Path.home() / 'unixnu-marble8796-build')))
cache = Path(os.environ.get('MARBLE_IIG_CACHE', str(Path(__file__).resolve().parents[1] / 'legacy-xnu/iig')))
manifest = json.loads((cache / 'manifest.json').read_text())
for name, expected in manifest['inputs'].items():
    assert hashlib.sha256((root / 'xnu' / name).read_bytes()).hexdigest() == expected, 'IIG source input changed: ' + name
args = sys.argv[1:]
definition = Path(args[args.index('--def') + 1])
header = Path(args[args.index('--header') + 1])
implementation = Path(args[args.index('--impl') + 1])
assert definition.suffix == '.iig'
assert definition.name.replace('.iig', '.h') == header.name
assert definition.name + '.cpp' == implementation.name
for target in (header, implementation):
    payload = (cache / 'generated' / target.name).read_bytes()
    assert hashlib.sha256(payload).hexdigest() == manifest['generated'][target.name]
    target.write_bytes(payload)
print('Pinned legacy IIG source:', definition.name)
