/* Temporary mode-7 BSD disk integration. Minor 0: whole LUN; minor 1: userdata.
 * No root selection, filesystem mount or data-write command is enabled here.
 */
#include <sys/buf.h>
#include <sys/conf.h>
#include <sys/disk.h>
#include <sys/fcntl.h>
#include <sys/vnode.h>
#include <sys/ucred.h>
#include <kern/locks.h>

namespace marble_block {
using namespace marble_scsi;
static State *host;
static uint64_t first_lba, part_blocks, disk_blocks;
static uint32_t sector_bytes;
static int disk_major=-1;
static uint32_t strategy_reads;
static LCK_GRP_DECLARE(lock_group,"marble_ufs_block");
static LCK_MTX_DECLARE(io_lock,&lock_group);

static bool io_range(int64_t block,uint32_t count,uint64_t bytes,uint64_t &offset) {
    if (block<0 || (uint64_t)block>UINT64_MAX/512) return false;
    offset=(uint64_t)block*512;
    return offset<=bytes && count<=bytes-offset;
}
static bool valid_device(dev_t dev) {
    return host && major(dev)==disk_major && minor(dev)<=1;
}
static int open_disk(dev_t dev,int flags,int,struct proc *) {
    if (!valid_device(dev)) return ENXIO;
    return flags&FWRITE ? EROFS : 0;
}
static int close_disk(dev_t dev,int,int,struct proc *) {
    return valid_device(dev) ? 0 : ENXIO;
}
static int ioctl_disk(dev_t dev,u_long cmd,caddr_t data,int,struct proc *) {
    if (!valid_device(dev)) return ENXIO;
    switch(cmd) {
    case DKIOCGETBLOCKSIZE: *(uint32_t *)data=512; return 0;
    case DKIOCSETBLOCKSIZE: return *(uint32_t *)data==512 ? 0 : EINVAL;
    case DKIOCGETPHYSICALBLOCKSIZE: *(uint32_t *)data=sector_bytes; return 0;
    case DKIOCGETBLOCKCOUNT:
        *(uint64_t *)data=(minor(dev) ? part_blocks : disk_blocks)*(sector_bytes/512); return 0;
    case DKIOCISWRITABLE: *(uint32_t *)data=0; return 0;
    case DKIOCGETMAXBLOCKCOUNTREAD: *(uint64_t *)data=bounce_size/512; return 0;
    case DKIOCGETMAXBLOCKCOUNTWRITE: *(uint64_t *)data=0; return 0;
    default: return ENOTTY;
    }
}
static int size_disk(dev_t dev) {
    if (!valid_device(dev)) return -1;
    uint64_t n=(minor(dev) ? part_blocks : disk_blocks)*(sector_bytes/512);
    return (int)(n>INT_MAX ? INT_MAX : n);
}
static void strategy(buf_t bp) {
    const uint32_t count=buf_count(bp);
    const dev_t dev=buf_device(bp);
    uint64_t offset=0;
    int error=0;
    caddr_t address=nullptr;
    buf_setresid(bp,count);
    if (!valid_device(dev)) error=ENXIO;
    else if (!(buf_flags(bp)&B_READ)) error=EROFS;
    else if (!io_range(buf_blkno(bp),count,
        (minor(dev) ? part_blocks : disk_blocks)*sector_bytes,offset)) error=EINVAL;
    if (error || !count) {
        if (error) buf_seterror(bp,error);
        buf_biodone(bp);
        return;
    }
    if (buf_map(bp,&address)) {
        buf_seterror(bp,EIO); buf_biodone(bp); return;
    }
    lck_mtx_lock(&io_lock);
    ++strategy_reads;
    for (uint32_t done=0;done<count;) {
        const uint64_t position=offset+done;
        const uint32_t skip=(uint32_t)(position%sector_bytes);
        const uint32_t remaining=count-done;
        const uint32_t want=remaining<bounce_size-skip ? remaining : bounce_size-skip;
        const uint32_t n=(skip+want+sector_bytes-1)/sector_bytes;
        const uint64_t lba=(minor(dev) ? first_lba : 0)+position/sector_bytes;
        if (lba>UINT32_MAX) { error=EINVAL; break; }
        error=blocks(*host,(uint32_t)lba,(uint16_t)n,sector_bytes);
        if (error) break;
        memcpy(address+done,buffer(*host)+skip,want);
        done+=want;
        buf_setresid(bp,count-done);
    }
    lck_mtx_unlock(&io_lock);
    buf_unmap(bp);
    if (error) buf_seterror(bp,error);
    buf_biodone(bp);
}
static struct bdevsw operations;

static int cached_read(dev_t dev,daddr64_t block,int count,uint8_t *destination) {
    vnode_t vp=nullptr;
    int error=bdevvp(dev,&vp);
    if (error) return error;
    buf_t bp=nullptr;
    error=buf_meta_bread(vp,block,count,NOCRED,&bp);
    if (!error && bp && !buf_resid(bp)) memcpy(destination,(void *)buf_dataptr(bp),count);
    else if (!error) error=EIO;
    if (bp) buf_brelse(bp);
    vnode_put(vp);
    return error;
}
static int rejected_io(dev_t dev,daddr64_t block,bool is_read,uint8_t *storage) {
    vnode_t vp=nullptr;
    int error=bdevvp(dev,&vp);
    if (error) return error;
    buf_t bp=buf_alloc(vp);
    if (!bp) { vnode_put(vp); return ENOMEM; }
    buf_setdataptr(bp,(uintptr_t)storage);
    buf_setsize(bp,512);
    buf_setcount(bp,512);
    buf_setblkno(bp,block);
    // This manually submitted iobuf bypasses buffered-write accounting, just
    // like physio's raw buffers. Completion must not decrement v_numoutput.
    buf_setflags(bp,B_RAW);
    if (is_read) buf_setflags(bp,B_READ);
    else buf_clearflags(bp,B_READ);
    bdevsw[disk_major].d_strategy(bp);
    error=buf_biowait(bp);
    if (buf_resid(bp)!=512) error=EIO;
    buf_free(bp);
    vnode_put(vp);
    return error;
}
} // namespace marble_block

static void marble_block_setup(marble_scsi::State &s,uint32_t sector,
    uint64_t first,uint64_t count,uint64_t total) {
    using namespace marble_block;
    marble_block::host=&s; sector_bytes=sector; first_lba=first; part_blocks=count; disk_blocks=total;
    operations.d_open=open_disk; operations.d_close=close_disk;
    operations.d_strategy=strategy; operations.d_ioctl=ioctl_disk;
    operations.d_dump=eno_dump; operations.d_psize=size_disk; operations.d_type=D_DISK;
    disk_major=bdevsw_add(-1,&operations);
    if (disk_major<0) fail(s,17,ENXIO);
}

[[noreturn]] static void marble_block_probe(marble_scsi::State &s,uint32_t sector,
    uint64_t first,uint64_t count,uint64_t total) {
    using namespace marble_block;
    marble_block_setup(s,sector,first,count,total);
    const dev_t disk=makedev(disk_major,0), part=makedev(disk_major,1);
    uint8_t data[4096], expected[512];
    const uint32_t before=strategy_reads;
    int error=cached_read(disk,sector/512,sector,data);
    if (error) fail(s,18,error);
    if (strategy_reads==before || memcmp(data,"EFI PART",8)) fail(s,19,EIO);
    const uint32_t length=le32(data+12), expected_crc=le32(data+16);
    if (length<92 || length>sector) fail(s,19,EINVAL);
    bzero(data+16,4);
    if (crc32(data,length)!=expected_crc) fail(s,19,EIO);
    error=blocks(s,(uint32_t)first,1,sector);
    if (error) fail(s,20,error);
    memcpy(expected,buffer(s)+512,sizeof(expected));
    error=cached_read(part,1,512,data);
    if (error || memcmp(expected,data,512)) fail(s,21,error ? error : EIO);
    const uint32_t read_count=strategy_reads;
    if (open_disk(part,FWRITE,0,nullptr)!=EROFS ||
        rejected_io(part,0,false,data)!=EROFS ||
        rejected_io(part,-1,true,data)!=EINVAL ||
        rejected_io(part,(daddr64_t)(count*(sector/512)),true,data)!=EINVAL ||
        strategy_reads!=read_count) fail(s,22,EIO);
    restore(s);
    panic("MARBLE UFS BSD READ OK DEV=%llx CHECKS=%llx",
        ((uint64_t)(uint32_t)disk_major<<32)|1u,0x1full);
}
