/* Diagnostic only: LUN 0 INQUIRY, capacity and primary GPT reads.
 * Mode 6 additionally permits one guarded Device W-LUN ACTIVE command.
 * No data-write CDB, no block-device registration, no filesystem mount.
 * Derived from the polled UFSHCI layout in UniXNU-negroni patch 0028.
 */
#include <vm/vm_kern.h>
#include <vm/pmap.h>
#include <arm/caches_internal.h>
#include <kern/clock.h>
#include <sys/errno.h>
extern "C" ppnum_t pmap_find_phys(pmap_t, addr64_t);

namespace marble_scsi {
constexpr uint32_t bounce_offset = 0x4000;
constexpr uint32_t bounce_size = 0x8000;
constexpr uint32_t allocation_size = bounce_offset + bounce_size;
struct Utrd { uint32_t words[8]; };
struct Ucd {
    uint8_t command[512];
    uint8_t response[512];
    uint32_t prdt[4];
};
static_assert(sizeof(Utrd) == 32, "UTRD ABI");
static_assert(sizeof(Ucd) == 1040, "command descriptor ABI");
struct State {
    vm_offset_t registers, memory;
    uint64_t physical, detail;
    uint32_t saved_ie, saved_lo, saved_hi, saved_run;
    uint8_t tag;
    bool owns_host, stop_on_sense, allow_active, active_attempted;
    uint8_t sense_key, sense_asc, sense_ascq;
    bool sense_valid;
};

struct SenseInfo {
    uint16_t length;
    uint8_t format, key, asc, ascq;
    bool valid;
};
static SenseInfo parse_sense(const uint8_t *response, uint32_t size) {
    SenseInfo result = {};
    result.key=result.asc=result.ascq=0xff;
    if (size < 34) return result;
    result.length=((uint16_t)response[32]<<8)|response[33];
    if (!result.length || result.length > size-34) return result;
    const uint8_t *sense=response+34;
    result.format=sense[0]&0x7f;
    if ((result.format==0x70 || result.format==0x71) && result.length>=14 && sense[7]>=6) {
        result.key=sense[2]&0x0f; result.asc=sense[12]; result.ascq=sense[13];
        result.valid=true;
    } else if ((result.format==0x72 || result.format==0x73) && result.length>=4) {
        result.key=sense[1]&0x0f; result.asc=sense[2]; result.ascq=sense[3];
        result.valid=true;
    }
    return result;
}

static uint32_t read(State &s, uint32_t off) {
    return *(volatile const uint32_t *)(s.registers + off);
}
static void write(State &s, uint32_t off, uint32_t value) {
    *(volatile uint32_t *)(s.registers + off) = value;
    __asm__ volatile("dsb sy" ::: "memory");
}
static void sync(State &s) {
    flush_dcache64(s.physical, allocation_size, TRUE);
    __asm__ volatile("dsb sy" ::: "memory");
}
static uint8_t *buffer(State &s) { return (uint8_t *)(s.memory + bounce_offset); }

static void restore(State &s) {
    // Both callers immediately panic/reset. Do not deliver a retained firmware
    // completion interrupt to an XNU handler that has not claimed this host.
    __asm__ volatile("msr daifset, #15" ::: "memory");
    /* Never redirect the host away from a request that may still be active.
     * The permanent allocation remains alive even if cancellation fails.
     */
    if (s.owns_host && read(s, 0x58) == 0) {
        write(s, 0x60, 0);
        write(s, 0x50, s.saved_lo);
        write(s, 0x54, s.saved_hi);
        write(s, 0x60, s.saved_run);
        write(s, 0x24, s.saved_ie);
        s.owns_host = false;
    }
}
[[noreturn]] static void fail(State &s, uint32_t stage, int error) {
    restore(s);
    panic("MARBLE UFS SCSI FAIL STAGE:ERR=%llx DETAIL=%llx",
        ((uint64_t)stage << 32) | (uint32_t)error, s.detail);
}

static bool allowed_cdb(const uint8_t *cdb, unsigned size, uint32_t len,
    uint8_t lun, bool allow_active) {
    if (!cdb || !size || size>16 || len>bounce_size) return false;
    if (cdb[0]==0x1b) {
        const uint8_t active[6]={0x1b,0,0,0,0x10,0};
        return allow_active && lun==0xd0 && !len && size==sizeof(active) &&
            memcmp(cdb,active,sizeof(active))==0;
    }
    return lun==0 && (cdb[0]==0x00 || cdb[0]==0x03 || cdb[0]==0x12 ||
        cdb[0]==0x25 || cdb[0]==0x28);
}
static int command(State &s, const uint8_t *cdb, unsigned size, uint32_t len,
    uint8_t lun=0) {
    /* Hard allowlist. No caller can issue WRITE, UNMAP, FORMAT or firmware CDBs. */
    if (!allowed_cdb(cdb,size,len,lun,s.allow_active)) return EINVAL;
    s.sense_valid=false;
    if (read(s, 0x58)) return EBUSY;
    auto *trd = (Utrd *)s.memory;
    auto *ucd = (Ucd *)(s.memory + 0x1000);
    bzero(trd, sizeof(*trd));
    bzero(ucd, sizeof(*ucd));
    bzero(buffer(s), bounce_size);
    ucd->command[0] = 0x01;
    ucd->command[1] = len ? 0x40 : 0;
    ucd->command[2] = lun; // data LUN 0; ACTIVE command only to Device W-LUN
    ucd->command[3] = ++s.tag;
    for (unsigned i = 0; i < 4; i++) ucd->command[12+i] = (uint8_t)(len >> (24-8*i));
    memcpy(ucd->command+16, cdb, size);
    const uint64_t address = s.physical + 0x1000;
    trd->words[0] = (1u << 28) | ((len ? 2u : 0u) << 25) | (1u << 24);
    trd->words[2] = 0x0f;
    trd->words[4] = (uint32_t)address;
    trd->words[5] = (uint32_t)(address >> 32);
    trd->words[6] = (128u << 16) | 128u;
    if (len) {
        const uint64_t bounce = s.physical + bounce_offset;
        ucd->prdt[0] = (uint32_t)bounce;
        ucd->prdt[1] = (uint32_t)(bounce >> 32);
        ucd->prdt[3] = len-1;
        trd->words[7] = (256u << 16) | 1;
    }
    sync(s);
    write(s, 0x58, 1);
    uint64_t timeout;
    nanoseconds_to_absolutetime(2ull * 1000 * 1000 * 1000, &timeout);
    const uint64_t start = mach_absolute_time();
    while (read(s, 0x58) & 1) {
        if (mach_absolute_time() - start >= timeout) {
            write(s, 0x5c, ~1u);
            // Flush before reading the OCS; descriptors are permanent on failure.
            sync(s);
            s.detail = s.physical;
            return ETIMEDOUT;
        }
        delay(1);
    }
    sync(s);
    write(s, 0x20, 1u); // acknowledge only this slot's transfer completion
    const uint32_t ocs = trd->words[2] & 0x0f;
    s.detail = ((uint64_t)cdb[0] << 56) | ((uint64_t)ocs << 32) |
        ((uint64_t)ucd->response[0] << 24) | ((uint64_t)ucd->response[6] << 8) |
        ucd->response[7];
    if (!ocs && ucd->response[0]==0x21 && ucd->response[2]==lun &&
        ucd->response[3]==s.tag && ucd->response[7]==2) {
        // Preserve the first CHECK CONDITION before REQUEST SENSE or a retry
        // can change it. Mode 5 stops without any power-mode command.
        const SenseInfo sense=parse_sense(ucd->response,sizeof(ucd->response));
        s.sense_valid=sense.valid;
        s.sense_key=sense.key; s.sense_asc=sense.asc; s.sense_ascq=sense.ascq;
        if (s.stop_on_sense) {
        const uint64_t packed=((uint64_t)sense.length<<48)|((uint64_t)sense.format<<40)|
            ((uint64_t)sense.key<<32)|((uint64_t)sense.asc<<24)|((uint64_t)sense.ascq<<16)|
            ((uint64_t)sense.valid<<8);
        restore(s);
        panic("MARBLE UFS SENSE RAW=%llx LEN:FMT:KEY:ASC:ASCQ:VALID=%llx",s.detail,packed);
        }
    }
    if (ocs || ucd->response[0] != 0x21 || ucd->response[6] || ucd->response[7] ||
        ucd->response[2] != lun || ucd->response[3] != s.tag) return EIO;
    // Read commands must transfer their full expected data, not under/overflow.
    if (ucd->response[1] & 0x60) return EIO;
    return 0;
}
static int retry(State &s, const uint8_t *cdb, unsigned size, uint32_t len) {
    int error = command(s, cdb, size, len);
    // Only the measured NOT READY / INITIALIZING COMMAND REQUIRED condition
    // authorizes one ACTIVE request. No repeated power commands on failure.
    if (error==EIO && s.allow_active && !s.active_attempted && s.sense_valid &&
        s.sense_key==2 && s.sense_asc==4 && s.sense_ascq==2) {
        s.active_attempted=true;
        kprintf("MARBLE UFS ACTIVE: one Device W-LUN initialization request\n");
        const uint8_t active[6]={0x1b,0,0,0,0x10,0};
        error=command(s,active,sizeof(active),0,0xd0);
        if (error) fail(s,16,error);
        delay(10000);
        return command(s,cdb,size,len);
    }
    if (error != EIO || (s.detail & 0xff) != 2) return error;
    // One bounded REQUEST SENSE for bootloader unit-attention, then retry once.
    const uint8_t sense[6] = {0x03, 0, 0, 0, 18, 0};
    error = command(s, sense, sizeof(sense), 18);
    return error ? error : command(s, cdb, size, len);
}
static uint32_t be32(const uint8_t *b) {
    return ((uint32_t)b[0]<<24)|((uint32_t)b[1]<<16)|((uint32_t)b[2]<<8)|b[3];
}
static uint32_t le32(const uint8_t *b) {
    return b[0]|((uint32_t)b[1]<<8)|((uint32_t)b[2]<<16)|((uint32_t)b[3]<<24);
}
static uint64_t le64(const uint8_t *b) { return le32(b)|((uint64_t)le32(b+4)<<32); }
static uint32_t crc32(const uint8_t *b, uint32_t n) {
    uint32_t c = ~0u;
    for (uint32_t i=0; i<n; i++) {
        c ^= b[i];
        for (unsigned bit=0; bit<8; bit++) c=(c>>1)^(0xedb88320u & (0u-(c&1)));
    }
    return ~c;
}
static int blocks(State &s, uint32_t lba, uint16_t count, uint32_t blocksize) {
    if (!count || count > bounce_size/blocksize) return EINVAL;
    const uint8_t cdb[10] = {0x28,0,(uint8_t)(lba>>24),(uint8_t)(lba>>16),
        (uint8_t)(lba>>8),(uint8_t)lba,0,(uint8_t)(count>>8),(uint8_t)count,0};
    return retry(s, cdb, sizeof(cdb), count*blocksize);
}
} // namespace marble_scsi

#include "marble_ufs_block.inc"

static void marble_ufs_scsi_probe(vm_offset_t mapped, unsigned mode) {
    using namespace marble_scsi;
    static State s = {};
    s.registers = mapped;
    s.stop_on_sense=(mode==5);
    s.allow_active=(mode>=6);
    s.detail = ((uint64_t)read(s,0x34)<<32)|read(s,0x30);
    if (!(read(s,0x34)&1) || (read(s,0x30)&3)!=3 || read(s,0x58)) fail(s,1,EBUSY);
    if (kmem_alloc_contig(kernel_map, &s.memory, allocation_size, PAGE_MASK, 0, 0,
        (kma_flags_t)(KMA_DATA|KMA_ZERO|KMA_PERMANENT), VM_KERN_MEMORY_IOKIT) != KERN_SUCCESS) fail(s,2,ENOMEM);
    const ppnum_t pn=pmap_find_phys(kernel_pmap,(addr64_t)s.memory);
    if (!pn) fail(s,2,ENOMEM);
    s.physical=ptoa_64(pn);
    s.detail=s.physical;
    if ((s.physical&0xfff) ||
        ((s.physical+allocation_size-1)>>32 && !(read(s,0)&(1u<<24)))) fail(s,3,EINVAL);
    // Check all pages really belong to this physically contiguous allocation.
    for (uint32_t offset=0; offset<allocation_size; offset+=PAGE_SIZE) {
        if (ptoa_64(pmap_find_phys(kernel_pmap,(addr64_t)s.memory+offset)) != s.physical+offset)
            fail(s,3,EINVAL);
    }
    // Do not modify SMMU here: first measure whether the retained boot state
    // allows this owned buffer. A timeout is a failure, never a synthetic success.
    s.saved_ie=read(s,0x24); s.saved_lo=read(s,0x50);
    s.saved_hi=read(s,0x54); s.saved_run=read(s,0x60);
    if (read(s,0x58)) fail(s,4,EBUSY);
    write(s,0x24,0); s.owns_host=true;
    write(s,0x60,0);
    write(s,0x50,(uint32_t)s.physical); write(s,0x54,(uint32_t)(s.physical>>32));
    write(s,0x60,1);
    if (read(s,0x50)!=(uint32_t)s.physical || read(s,0x54)!=(uint32_t)(s.physical>>32) ||
        !(read(s,0x60)&1)) fail(s,4,EIO);
    const uint8_t inquiry[6]={0x12,0,0,0,36,0};
    int error=retry(s,inquiry,sizeof(inquiry),36);
    if (error) fail(s,5,error);
    if ((buffer(s)[0]&0x1f)!=0) fail(s,5,ENXIO);
    const uint8_t capacity[10]={0x25};
    error=retry(s,capacity,sizeof(capacity),8);
    if (error) fail(s,6,error);
    const uint32_t last=be32(buffer(s)), sector=be32(buffer(s)+4);
    s.detail=((uint64_t)last<<32)|sector;
    if ((sector!=4096 && sector!=512) || last==0xffffffff || last<3) fail(s,7,EINVAL);
    // Exact known Android geometry: never scan an unexpected LUN layout.
    if (((uint64_t)last+1)*sector != 253461790720ull) fail(s,7,EINVAL);
    error=blocks(s,1,1,sector);
    if (error) fail(s,8,error);
    uint8_t *b=buffer(s);
    if (memcmp(b,"EFI PART",8)!=0 || le32(b+8)!=0x00010000 || le64(b+24)!=1)
        fail(s,9,EINVAL);
    const uint32_t header_size=le32(b+12), header_crc=le32(b+16);
    if (header_size<92 || header_size>sector || le32(b+20)!=0) fail(s,9,EINVAL);
    bzero(b+16,4);
    if (crc32(b,header_size)!=header_crc) fail(s,10,EIO);
    const uint64_t entry_lba=le64(b+72), first_usable=le64(b+40), last_usable=le64(b+48);
    const uint32_t entries=le32(b+80), entry_size=le32(b+84), entry_crc=le32(b+88);
    if (entry_size!=128 || !entries || entries>bounce_size/128 ||
        entry_lba<2 || entry_lba>last || first_usable>last_usable || last_usable>=last ||
        (entries*128+sector-1)/sector>last-entry_lba+1) fail(s,11,EINVAL);
    error=blocks(s,(uint32_t)entry_lba,(uint16_t)((entries*128+sector-1)/sector),sector);
    if (error) fail(s,12,error);
    if (crc32(b,entries*128)!=entry_crc) fail(s,13,EIO);
    const char target[]="userdata";
    uint64_t found_first=0, found_count=0;
    for (uint32_t i=0; i<entries; i++) {
        const uint8_t *e=b+i*128;
        bool matches=true;
        for (unsigned k=0; k<sizeof(target); k++) {
            if (e[56+k*2]!=(uint8_t)target[k] || e[57+k*2]!=0) matches=false;
        }
        if (!matches) continue;
        if (found_count) fail(s,14,EINVAL);
        const uint64_t start=le64(e+32), end=le64(e+40);
        if (start<first_usable || end>last_usable || end<start) fail(s,14,EINVAL);
        found_first=start; found_count=end-start+1;
    }
    s.detail=found_first;
    if (!found_count || found_first*sector!=12727615488ull ||
        found_count*sector!=240734154752ull) fail(s,15,EINVAL);
    if (mode==9) {
        marble_block_setup(s,sector,found_first,found_count,(uint64_t)last+1);
        return; // Keep the owned DMA queue for subsequent normal VFS reads.
    }
    if (mode==7) marble_block_probe(s,sector,found_first,found_count,(uint64_t)last+1);
    restore(s);
    panic("MARBLE UFS GPT OK USERDATA FIRST:COUNT=%llx,%llx",found_first,found_count);
}
