"""Report the actual UFS solid-state media type to HFS (dry run by default)."""
import argparse
from pathlib import Path
from datetime import datetime

p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--source',type=Path,default=Path.home()/'unixnu-marble8796-build/xnu/iokit/bsddev/marble_ufs_block.inc')
p.add_argument('--apply',action='store_true')
a=p.parse_args()
old=a.source.read_text()
anchor='    case DKIOCGETPHYSICALBLOCKSIZE: *(uint32_t *)data=sector_bytes; return 0;'
assert old.count(anchor)==1
addition='''
    // UFS is solid-state storage. Let HFS disable rotational-media relocation.
    case DKIOCISSOLIDSTATE: *(uint32_t *)data=1; return 0;'''
if 'case DKIOCISSOLIDSTATE:' in old:
    assert addition in old
    print('Already reports solid-state media')
else:
    new=old.replace(anchor,anchor+addition,1)
    if a.apply:
        backup=a.source.with_name(a.source.name+datetime.now().strftime('.before-ssd-%Y%m%d-%H%M%S'))
        assert not backup.exists()
        backup.write_text(old)
        a.source.write_text(new)
        print('Applied; backup:',backup)
    else:
        print('Dry run: add DKIOCISSOLIDSTATE uint32_t=1; all I/O unchanged')
