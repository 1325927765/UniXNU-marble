"""Apply software-only AMFI support, replacing broad root platform grants."""
from pathlib import Path
import subprocess
import zipfile

root = Path.home()/'unixnu-marble8796-build'
src = root/'xnu'
stage = root/'amfi-stage'
stage.mkdir(exist_ok=True)
with zipfile.ZipFile(Path.home()/'unixnu-marble-kit/amfi-sources.zip') as z:
    z.extractall(stage)
for patch in sorted(stage.glob('*.patch')):
    subprocess.run(['git','apply','--check',str(patch)],cwd=src,check=True)
    subprocess.run(['git','apply',str(patch)],cwd=src,check=True)
p = src/'bsd/kern/marble_amfi.c'
text = p.read_text()
old = 'if (mp != NULL && (vfs_flags(mp) & MNT_ROOTFS)) {'
new = ('if (mp != NULL && (vfs_flags(mp) & (MNT_ROOTFS | MNT_RDONLY)) == '
       '(MNT_ROOTFS | MNT_RDONLY) && marble_ios16_hash_allowed(cs_blob)) {')
assert text.count(old) == 1
text = text.replace(old,new)
anchor = '#include <security/mac_policy.h>'
assert text.count(anchor) == 1
text = text.replace(anchor,anchor+'\n#include "marble_ios16_cdhashes.inc"')
# Correct the reference comments to describe the actual bounded policy.
text = text.replace('marks every binary on the root\n * filesystem instead',
                    'marks only exact pinned iOS CDHash/type entries on the readonly root\n * filesystem instead')
text = text.replace('Every signed binary on the root filesystem is a',
                    'Only pinned iOS CDHash/type entries on the readonly root qualify as a')
p.write_text(text)
(src/'bsd/kern/marble_ios16_cdhashes.inc').write_bytes((stage/'marble_ios16_cdhashes.inc').read_bytes())
print('AMFI XML support + exact pinned readonly-root platform policy applied')
