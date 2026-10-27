"""Use device-tree machine/product/target names on Marble; dry-run by default."""
from pathlib import Path
from datetime import datetime
import argparse
import re

p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--source-root',type=Path,required=True)
p.add_argument('--apply',action='store_true')
a=p.parse_args(); r=a.source_root
names=['bsd/kern/kern_mib.c','iokit/Kernel/arm/MarblePlatformExpert.cpp']
old={name:(r/name).read_text() for name in names}; new=dict(old)
key='#if XNU_TARGET_OS_OSX && defined(__arm64__)'
assert new[names[0]].count(key)==1
new[names[0]]=new[names[0]].replace(key,key+' && !defined(ARM64_BOARD_CONFIG_MARBLE)\n/* Marble UI identity comes from the custom device tree, not iOS-on-Mac. */')
s=new[names[1]]
for method in ('getTargetName','getProductName'):
    s,n=re.subn(r'\s*bool '+method+r'\(char \*name, int maxLength\) APPLE_KEXT_OVERRIDE;', '', s)
    assert n==1,(method,n)
    s,n=re.subn(r'bool\nMarblePlatformExpert::'+method+r'\(char \*name, int maxLength\)\n\{.*?\n\}', '',s,flags=re.S)
    assert n==1,(method,n)
new[names[1]]=s
print('Validated: Marble uses standard device-tree names for hw.machine/model/product/target')
if a.apply:
    backup=r/'trace-backups'/datetime.now().strftime('%Y%m%d-ui-identity-%H%M%S')
    for name in names:
        dest=backup/name;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_text(old[name])
        (r/name).write_text(new[name])
    print('Applied; backup:',backup)
