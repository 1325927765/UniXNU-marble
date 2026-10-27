"""Publish the existing read-only UFS root through block and raw devfs nodes."""
from datetime import datetime
from pathlib import Path

p=Path.home()/'unixnu-marble8796-build/xnu/iokit/bsddev/marble_ufs_block.inc'
old=p.read_text()
if 'MARBLE UFS DEVFS' in old:
    raise SystemExit('already installed')
text=old.replace('#include <sys/buf.h>', '#include <sys/buf.h>\n#include <sys/uio.h>\n#include <sys/stat.h>\n#include <miscfs/devfs/devfs.h>',1)
anchor='static struct bdevsw operations;'
assert text.count(anchor)==1
text=text.replace(anchor,'''static struct bdevsw operations;
static struct cdevsw raw_operations;
static int raw_major=-1;
static dev_t block_device(dev_t dev) {
    return makedev(disk_major,minor(dev));
}
static int raw_open(dev_t dev,int flags,int type,struct proc *p) {
    return major(dev)==raw_major ? open_disk(block_device(dev),flags,type,p) : ENXIO;
}
static int raw_close(dev_t dev,int flags,int type,struct proc *p) {
    return close_disk(block_device(dev),flags,type,p);
}
static int raw_ioctl(dev_t dev,u_long cmd,caddr_t data,int flags,struct proc *p) {
    return ioctl_disk(block_device(dev),cmd,data,flags,p);
}
static int raw_write(dev_t,struct uio *,int) { return EROFS; }
static int raw_read(dev_t dev,struct uio *uio,int) {
    dev_t blockdev=block_device(dev);
    if (!valid_device(blockdev)) return ENXIO;
    if (uio_offset(uio)<0 || uio_resid(uio)<0) return EINVAL;
    const uint64_t bytes=(minor(dev) ? part_blocks : disk_blocks)*sector_bytes;
    uint8_t data[4096];
    while (uio_resid(uio)>0) {
        uint64_t offset=(uint64_t)uio_offset(uio);
        if (offset>=bytes) return offset==bytes ? 0 : EINVAL;
        uint32_t count=(uint64_t)uio_resid(uio)>sizeof(data) ? sizeof(data) : (uint32_t)uio_resid(uio);
        if (count>bytes-offset) count=(uint32_t)(bytes-offset);
        uint32_t skip=(uint32_t)(offset%sector_bytes);
        uint64_t lba=(minor(dev) ? first_lba : 0)+offset/sector_bytes;
        if (lba>UINT32_MAX) return EINVAL;
        lck_mtx_lock(&io_lock);
        int error=blocks(*host,(uint32_t)lba,(uint16_t)((skip+count+sector_bytes-1)/sector_bytes),sector_bytes);
        if (!error) memcpy(data,buffer(*host)+skip,count);
        lck_mtx_unlock(&io_lock);
        if (error) return error;
        error=uiomove((caddr_t)data,count,uio);
        if (error) return error;
    }
    return 0;
}''',1)
anchor='    if (disk_major<0) fail(s,17,ENXIO);'
assert text.count(anchor)==1
text=text.replace(anchor,anchor+'''
    raw_operations.d_open=raw_open; raw_operations.d_close=raw_close;
    raw_operations.d_read=raw_read; raw_operations.d_write=raw_write;
    raw_operations.d_ioctl=raw_ioctl; raw_operations.d_stop=eno_stop;
    raw_operations.d_reset=eno_reset; raw_operations.d_select=eno_select;
    raw_operations.d_mmap=eno_mmap; raw_operations.d_strategy=eno_strat;
    raw_operations.d_reserved_1=eno_getc; raw_operations.d_reserved_2=eno_putc;
    raw_operations.d_type=D_DISK;
    raw_major=cdevsw_add_with_bdev(-1,&raw_operations,disk_major);
    if (raw_major<0) fail(s,17,ENXIO);
    if (!devfs_make_node(makedev(disk_major,1),DEVFS_BLOCK,UID_ROOT,GID_OPERATOR,0600,"marbleufs0") ||
        !devfs_make_node(makedev(raw_major,1),DEVFS_CHAR,UID_ROOT,GID_OPERATOR,0600,"rmarbleufs0"))
        fail(s,17,ENXIO);
    printf("MARBLE UFS DEVFS: /dev/marbleufs0 and /dev/rmarbleufs0 published readonly\\n");
''',1)
backup=Path.home()/'unixnu-marble8796-build/trace-backups'/datetime.now().strftime('%Y%m%d-ufs-devfs-%H%M%S')
backup.mkdir(parents=True,exist_ok=False)
(backup/p.name).write_text(old)
p.write_text(text)
print('patched',p,'backup',backup)
b=Path.home()/'unixnu-marble8796-build/xnu/bsd/kern/bsd_init.c'
base=b.read_text()
anchor='\t\tif (0 == (err = vfs_mountroot())) {\n'
assert base.count(anchor)==1 and 'MARBLE UFS ROOT SOURCE' not in base
(backup/b.name).write_text(base)
b.write_text(base.replace(anchor,anchor+'''
#if defined(MARBLE)
            unsigned int marble_source_mode=0;
            if (PE_parse_boot_argn("marble_ufs_probe", &marble_source_mode,
                sizeof(marble_source_mode)) && marble_source_mode==9 &&
                strcmp(rootdevice,"marbleufs0")==0) {
                struct mount *marble_root_mount=mountlist.tqh_first;
                if (!marble_root_mount || strcmp(marble_root_mount->mnt_vtable->vfc_name,"hfs"))
                    panic("MARBLE UFS ROOT SOURCE: expected HFS");
                strlcpy(vfs_statfs(marble_root_mount)->f_mntfromname,
                    "/dev/marbleufs0",sizeof(vfs_statfs(marble_root_mount)->f_mntfromname));
                printf("MARBLE UFS ROOT SOURCE: /dev/marbleufs0\\n");
            }
#endif
''',1))
print('patched',b)
