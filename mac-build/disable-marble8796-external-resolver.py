"""Use XNU's local UID/GID GUID mapping for the Marble iOS test board.

iOS has no macOS memberd service. Keep filesystem ACL evaluation enabled,
but avoid delegating group lookups to that absent external resolver.
"""
import argparse
from datetime import datetime
from pathlib import Path

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--source', type=Path, default=Path.home() / 'unixnu-marble8796-build/xnu/config/MASTER.arm64.marble')
p.add_argument('--apply', action='store_true')
a = p.parse_args()
old = a.source.read_text()
lines = [line for line in old.splitlines() if 'FILESYS_BASE = ' in line]
assert len(lines) == 1, 'Expected one board filesystem configuration'
line = lines[0]
assert ' bindfs ' in line and ' marble_hfs ' in line
if ' config_ext_resolver ' not in line:
    print('Already uses local group mapping:', a.source)
else:
    new = old.replace(line, line.replace(' config_ext_resolver ', ' '), 1)
    assert new.count('config_ext_resolver') == old.count('config_ext_resolver') - 1
    if a.apply:
        backup = a.source.with_name(a.source.name + datetime.now().strftime('.before-local-groups-%Y%m%d-%H%M%S'))
        assert not backup.exists()
        backup.write_text(old)
        a.source.write_text(new)
        print('Applied; backup:', backup)
    else:
        print('Dry run: remove only config_ext_resolver from FILESYS_BASE')
