"""Install pinned App trust-cache entries and a webbookmarksd decision diagnostic."""
import argparse
from datetime import datetime
import hashlib
from pathlib import Path
import re

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--source-root', type=Path, default=Path.home()/'unixnu-marble8796-build/xnu')
p.add_argument('--include', type=Path, default=Path.home()/'unixnu-marble8796-build/cryptex-cdhashes.inc')
p.add_argument('--apply', action='store_true')
a = p.parse_args()
names = ['bsd/kern/marble_amfi.c', 'bsd/kern/marble_ios16_cdhashes.inc']
old = {n: (a.source_root/n).read_bytes() for n in names}
table = a.include.read_bytes()
assert hashlib.sha256(table).hexdigest() == '996eb4ad782f5c743b4853351a31a55883794976e49cc59ca900de4f9ce88728'
def keys(data):
    return [bytes(int(v, 16) for v in re.findall(r'0x[0-9a-f]{2}', row))
            for row in data.decode().splitlines() if row.strip().startswith('{0x')]
old_keys, new_keys = keys(old[names[1]]), keys(table)
assert len(old_keys) == 2760 and len(new_keys) == 2790
assert new_keys == sorted(set(new_keys)) and set(old_keys).issubset(new_keys)
s = old[names[0]].decode()
anchor = '\tif (cs_blob != cs_blob->csb_ro_addr && cs_blob->csb_entitlements == NULL) {'
assert s.count(anchor) == 1
diagnostic = '''
    /* Bounded by exec of this one system daemon; does not grant any flags. */
    const char *marble_identity = csblob_get_identity(cs_blob);
    if (marble_identity != NULL && strcmp(marble_identity, "com.apple.webbookmarksd") == 0) {
        printf("MARBLE AMFI APP: webbookmarksd pinned=%d platform=%d root=%d readonly=%d physical_rw=%d\\n",
            marble_ios16_hash_allowed(cs_blob), !!(*cs_flags & CS_PLATFORM_BINARY),
            mp != NULL && !!(vfs_flags(mp) & MNT_ROOTFS), root_is_readonly,
            marble_physical_rootrw);
    }
'''
new = {names[0]: s.replace(anchor, diagnostic + anchor, 1).encode(), names[1]: table}
print('Validated: 2760 existing + 30 App exact pins; unchanged root/write decision gate')
if a.apply:
    backup = a.source_root/'trace-backups'/datetime.now().strftime('%Y%m%d-cryptex-amfi-%H%M%S')
    for n in names:
        dest = backup/n
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(old[n])
    try:
        for n in names:
            (a.source_root/n).write_bytes(new[n])
    except Exception:
        for n in names:
            (a.source_root/n).write_bytes(old[n])
        raise
    print('Applied; backup:', backup)
