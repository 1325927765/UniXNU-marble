"""Promote 4K page counts before shifting, preserving the existing bounds checks."""
import difflib
import json
from pathlib import Path

r = Path.home() / 'unixnu-marble8796-build'
path = r / 'xnu/bsd/dev/memdev.c'
old = path.read_text()
before = 'mdev[devid].mdSize << 12'
after = '((uint64_t)mdev[devid].mdSize << 12)'
assert old.count(before) == 8, old.count(before)
assert after not in old, 'Already patched; do not apply twice'
new = old.replace(before, after)
path.write_text(new)
patch = ''.join(difflib.unified_diff(old.splitlines(True), new.splitlines(True),
                                  fromfile='a/bsd/dev/memdev.c', tofile='b/bsd/dev/memdev.c'))
(r / 'memdev-size64.patch').write_text(patch)
(r / 'memdev-size64.json').write_text(json.dumps(dict(replacements=8,
    input_field='uint32_t mdSize, count of 4096-byte pages',
    correction='Promote to uint64_t before byte-size conversion',
    bounds_checks_preserved=True, data_write_policy_unchanged=True,
    xnu8796_compiled=False), indent=2) + '\n')
print('Memory-device byte-size conversion promoted at 8 existing call sites')
