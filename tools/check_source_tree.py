#!/usr/bin/env python3
"""Offline source-only integrity and syntax checks; never access a device."""
import hashlib
import json
from pathlib import Path
import py_compile
import re
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
index = json.loads((ROOT / 'SOURCE-INDEX.json').read_text(encoding='utf-8'))
tracked = subprocess.check_output(['git', '-C', str(ROOT), 'ls-files', '-co', '--exclude-standard', '-z'])
paths = {p.decode('utf-8') for p in tracked.split(b'\0') if p} - {'SOURCE-INDEX.json'}
assert paths == {entry['path'] for entry in index['files']}, 'Source inventory does not cover the publication tree'
for entry in index['files']:
    path = ROOT / entry['path']
    data = path.read_bytes()
    assert len(data) == entry['bytes'], entry['path']
    assert hashlib.sha256(data).hexdigest() == entry['sha256'], entry['path']
    assert b'\0' not in data, 'Binary data: ' + entry['path']
    assert not re.search(rb'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----', data), entry['path']
    assert path.suffix.lower() not in {'.img', '.simg', '.ipsw', '.dmg', '.cdr', '.fd', '.exe', '.dll', '.mp4', '.mov', '.zip'}, entry['path']
with tempfile.TemporaryDirectory() as temp:
    files = [ROOT / e['path'] for e in index['files'] if e['path'].endswith('.py')]
    for i, path in enumerate(files):
        py_compile.compile(str(path), cfile=str(Path(temp) / f'{i}.pyc'), doraise=True)
print(f"PASS: {len(index['files'])} source/document files; {len(files)} Python files compile")
