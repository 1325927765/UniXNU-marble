"""Explicit DEVELOPMENT-only opt-in for the converted readonly HFS root."""
from datetime import datetime
from pathlib import Path

source=Path.home()/'unixnu-marble8796-build/xnu/bsd/kern/bsd_init.c'
old=source.read_text()
if 'marble_allow_unsealed_hfs_root' in old:
    raise SystemExit('development root policy already installed')
anchor='\t\tif (require_rootauth) {\n\t\t\t/* enforce sealedness */'
if old.count(anchor)!=1:
    raise SystemExit('root authentication source differs; no change')
policy='''#if defined(MARBLE) && (DEVELOPMENT || DEBUG)
        /* Converted HFS has no Apple sealed-root authentication. This explicit
         * development policy does not claim authentication or alter AMFI. */
        unsigned int marble_unsealed_hfs = 0;
        if (require_rootauth && PE_parse_boot_argn("marble_allow_unsealed_hfs_root",
            &marble_unsealed_hfs, sizeof(marble_unsealed_hfs)) && marble_unsealed_hfs == 1) {
            struct mount *mp = vnode_mount(rootvnode);
            if (mp == NULL || strcmp(mp->mnt_vtable->vfc_name, "hfs") ||
                !(mp->mnt_flag & MNT_RDONLY)) {
                panic("MARBLE ROOT POLICY: expected readonly HFS root");
            }
            printf("MARBLE ROOT POLICY: DEVELOPMENT unsealed readonly HFS opt-in; AMFI unchanged\\n");
            require_rootauth = FALSE;
        }
#endif

'''
backup=Path.home()/'unixnu-marble8796-build/trace-backups'/datetime.now().strftime('%Y%m%d-unsealed-hfs-%H%M%S')
backup.mkdir(parents=True,exist_ok=False)
(backup/'bsd_init.c').write_text(old)
source.write_text(old.replace(anchor,policy+anchor,1))
print(f'patched={source}\nbackup={backup / "bsd_init.c"}')
