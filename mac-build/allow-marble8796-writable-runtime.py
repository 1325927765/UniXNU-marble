"""Retain pinned iOS hashes and HFS atomic swaps on the opt-in UFS root.

Does not change the initial readonly root mount or sealed-root policy.
The driver export requires the actual partition writer to be enabled.
"""
from pathlib import Path
from datetime import datetime
root=Path.home()/'unixnu-marble8796-build/xnu'
backup=Path.home()/'unixnu-marble8796-build/trace-backups'/datetime.now().strftime('%Y%m%d-ufs-runtime-%H%M%S')
changes={}
p=root/'bsd/kern/marble_amfi.c'
old=p.read_text()
needle='(root_is_readonly || qemu_rootrw) && marble_ios16_hash_allowed(cs_blob)'
assert old.count(needle)==1
anchor='\tmount_t mp = vnode_mount(vp);'
assert old.count(anchor)==1
new=old.replace(anchor,anchor+'''
    extern int marble_ufs_root_write_enabled(void);
    int marble_physical_rootrw = mp != NULL &&
        strcmp(vfs_statfs(mp)->f_fstypename,"hfs")==0 &&
        strcmp(vfs_statfs(mp)->f_mntfromname,"/dev/marbleufs0")==0 &&
        marble_ufs_root_write_enabled();
''',1).replace(needle,'(root_is_readonly || qemu_rootrw || marble_physical_rootrw) && marble_ios16_hash_allowed(cs_blob)',1)
changes[p]=(old,new)
p=root/'bsd/vfs/kpi_vfs.c'
old=p.read_text()
needle='marble_qemu_writable_root == 1)\n'
assert old.count(needle)==1
anchor='\t\t\tuint32_t marble_qemu_writable_root = 0;'
assert old.count(anchor)==1
new=old.replace(anchor,anchor+'''
            extern int marble_ufs_root_write_enabled(void);
            mount_t marble_swap_mount=vnode_mount(*fvpp);
            int marble_physical_swap =
                (vfs_flags(marble_swap_mount) & MNT_ROOTFS) &&
                strcmp(vfs_statfs(marble_swap_mount)->f_fstypename,"hfs")==0 &&
                strcmp(vfs_statfs(marble_swap_mount)->f_mntfromname,"/dev/marbleufs0")==0 &&
                marble_ufs_root_write_enabled();
''',1)
start='\t\t\tif (PE_parse_boot_argn("marble_qemu_writable_root",'
assert new.count(start)==1
new=new.replace(start,'\t\t\tif ((PE_parse_boot_argn("marble_qemu_writable_root",',1)
new=new.replace(needle,'marble_qemu_writable_root == 1) || marble_physical_swap)\n',1)
changes[p]=(old,new)
backup.mkdir(parents=True,exist_ok=False)
for p,(old,new) in changes.items():
    (backup/p.name).write_text(old)
    p.write_text(new)
    print('patched',p)
print('backup',backup)
