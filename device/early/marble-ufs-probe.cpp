/* Modes 1-3 read UFSHCI registers only. Modes 4-5 enable read-only SCSI.
 * Mode 6 also permits one conditionally triggered Device W-LUN ACTIVE request.
 */
#include <pexpert/pexpert.h>
#include <pexpert/device_tree.h>
#include <libkern/libkern.h>
#include <mach/mach_types.h>

extern "C" vm_offset_t ml_io_map(vm_offset_t, vm_size_t);
extern "C" void marble_ufs_readonly_probe(void);
#include "marble_ufs_scsi.inc"

extern "C" void
marble_ufs_readonly_probe(void)
{
    unsigned int enabled = 0;
    if (!PE_parse_boot_argn("marble_ufs_probe", &enabled, sizeof(enabled)) ||
        ((enabled < 1 || enabled > 7) && enabled != 9)) {
        return;
    }
    DTEntry entry;
    const void *property = nullptr;
    unsigned int length = 0;
    if (SecureDTLookupEntry(nullptr, "/marble-ufs-probe", &entry) != kSuccess ||
        SecureDTGetProperty(entry, "reg", &property, &length) != kSuccess ||
        length != 2 * sizeof(uint64_t)) {
        kprintf("MARBLE UFS PROBE: missing or invalid ADT reg\n");
        return;
    }
    uint64_t reg[2];
    memcpy(reg, property, sizeof(reg));
    if (reg[0] != 0x01d84000 || reg[1] != 0x3000) {
        kprintf("MARBLE UFS PROBE: refusing unexpected MMIO range\n");
        return;
    }
    const vm_offset_t mapped = ml_io_map((vm_offset_t)reg[0], (vm_size_t)reg[1]);
    if (!mapped) {
        kprintf("MARBLE UFS PROBE: mapping failed\n");
        return;
    }
    /* Reading these UFSHCI status registers does not acknowledge interrupts.
     * Never read a doorbell through a write alias or clear an interrupt here.
     * A physical access fault must remain visible as a kernel exception.
     */
    const auto read32 = [mapped](unsigned int offset) -> uint32_t {
        return *(volatile const uint32_t *)(mapped + offset);
    };
    const uint32_t cap = read32(0x00);
    const uint32_t version = read32(0x08);
    const uint32_t hcs = read32(0x30);
    const uint32_t hce = read32(0x34);
    const uint32_t pending = read32(0x58);
    const uint32_t running = read32(0x60);
    kprintf("MARBLE UFS PROBE: CAP=%08x VER=%08x HCE=%08x HCS=%08x DBR=%08x RSR=%08x\n",
        cap, version, hce, hcs, pending, running);
    kprintf("MARBLE UFS PROBE: register reads complete; no DMA/SCSI issued\n");
    if (enabled == 3) {
        const uint32_t list_low = read32(0x50);
        const uint32_t list_high = read32(0x54);
        panic("MARBLE UFS QUEUE READ DBR:RSR=%llx BAU:BA=%llx",
            ((uint64_t)pending << 32) | running,
            ((uint64_t)list_high << 32) | list_low);
    }
    if (enabled >= 4) {
        marble_ufs_scsi_probe(mapped, enabled);
    }
    if (enabled == 2) {
        /* Deliberate diagnostic stop, rendered by the separately verified
         * panic witness: ARG0 contains HCE:HCS; ARG1 contains CAP:VER.
         */
        panic("MARBLE UFS READ OK HCE:HCS=%llx CAP:VER=%llx",
            ((uint64_t)hce << 32) | hcs, ((uint64_t)cap << 32) | version);
    }
}

static bool marble_ufs_select_root(char *name,unsigned size,dev_t *dev,u_int32_t *flags) {
    unsigned mode=0;
    if (!PE_parse_boot_argn("marble_ufs_probe",&mode,sizeof(mode)) || mode!=9) return false;
    char requested[32]={};
    if (!PE_parse_boot_argn("rd",requested,sizeof(requested)) || strcmp(requested,"marbleufs0"))
        panic("MARBLE UFS ROOT: mode 9 requires rd=marbleufs0");
    if (!marble_block::host || marble_block::disk_major<0)
        panic("MARBLE UFS ROOT: block device unavailable");
    *dev=makedev(marble_block::disk_major,1);
    *flags=0;
    strlcpy(name,"marbleufs0",size);
    return true;
}

extern "C" uint64_t marble_ufs_root_read_count(void) {
    return marble_block::strategy_reads;
}
