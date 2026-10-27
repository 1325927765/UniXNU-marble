"""Prepare an opt-in, userdata-partition-only UFS WRITE(10) path.

The script targets the Mac XNU checkout, but defaults to dry-run.  It never
boots a phone or issues SCSI commands; --apply only edits the source checkout
after making verified backups.
"""
from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path


ROOT = Path.home() / "unixnu-marble8796-build"
SCsi = ROOT / "xnu/iokit/bsddev/marble_ufs_scsi.inc"
BLOCK = ROOT / "xnu/iokit/bsddev/marble_ufs_block.inc"
PROBE = ROOT / "xnu/iokit/bsddev/marble_ufs_probe.inc"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"expected exactly one {label} anchor, found {count}")
    return text.replace(old, new, 1)


def transform_scsi(text: str) -> str:
    text = replace_once(
        text,
        "    uint8_t tag;\n    bool owns_host, stop_on_sense, allow_active, active_attempted;",
        "    uint8_t tag;\n"
        "    bool owns_host, stop_on_sense, allow_active, active_attempted;\n"
        "    bool write_enabled;\n"
        "    uint32_t write_sector_bytes;\n"
        "    uint64_t write_first_lba, write_block_count;",
        "State fields",
    )
    text = replace_once(
        text,
        "static bool allowed_cdb(const uint8_t *cdb, unsigned size, uint32_t len,\n"
        "    uint8_t lun, bool allow_active) {\n"
        "    if (!cdb || !size || size>16 || len>bounce_size) return false;\n"
        "    if (cdb[0]==0x1b) {\n"
        "        const uint8_t active[6]={0x1b,0,0,0,0x10,0};\n"
        "        return allow_active && lun==0xd0 && !len && size==sizeof(active) &&\n"
        "            memcmp(cdb,active,sizeof(active))==0;\n"
        "    }\n"
        "    return lun==0 && (cdb[0]==0x00 || cdb[0]==0x03 || cdb[0]==0x12 ||\n"
        "        cdb[0]==0x25 || cdb[0]==0x28);\n"
        "}\n"
        "static int command(State &s, const uint8_t *cdb, unsigned size, uint32_t len,\n"
        "    uint8_t lun=0) {\n"
        "    /* Hard allowlist. No caller can issue WRITE, UNMAP, FORMAT or firmware CDBs. */\n"
        "    if (!allowed_cdb(cdb,size,len,lun,s.allow_active)) return EINVAL;",
        "static bool allowed_cdb(const State &s, const uint8_t *cdb, unsigned size,\n"
        "    uint32_t len, uint8_t lun, bool allow_active, bool data_out) {\n"
        "    if (!cdb || !size || size>16 || len>bounce_size) return false;\n"
        "    if (cdb[0]==0x1b) {\n"
        "        const uint8_t active[6]={0x1b,0,0,0,0x10,0};\n"
        "        return allow_active && lun==0xd0 && !len && size==sizeof(active) &&\n"
        "            memcmp(cdb,active,sizeof(active))==0;\n"
        "    }\n"
        "    if (cdb[0]==0x2a) {\n"
        "        if (!data_out || !s.write_enabled || lun!=0 || size!=10 ||\n"
        "            cdb[1]!=0 || cdb[6]!=0 || cdb[9]!=0 || !s.write_sector_bytes) return false;\n"
        "        const uint64_t lba=((uint64_t)cdb[2]<<24)|((uint64_t)cdb[3]<<16)|\n"
        "            ((uint64_t)cdb[4]<<8)|cdb[5];\n"
        "        const uint32_t count=((uint32_t)cdb[7]<<8)|cdb[8];\n"
        "        if (!count || lba<s.write_first_lba || lba>UINT32_MAX ||\n"
        "            lba-s.write_first_lba>=s.write_block_count ||\n"
        "            count>s.write_block_count-(lba-s.write_first_lba) ||\n"
        "            count-1>UINT32_MAX-lba ||\n"
        "            len!=(uint64_t)count*s.write_sector_bytes ||\n"
        "            len>bounce_size || count>bounce_size/s.write_sector_bytes) return false;\n"
        "        return true;\n"
        "    }\n"
        "    if (cdb[0]==0x35) {\n"
        "        static const uint8_t sync[10]={0x35};\n"
        "        return s.write_enabled && !data_out && lun==0 && size==sizeof(sync) && !len &&\n"
        "            memcmp(cdb,sync,sizeof(sync))==0;\n"
        "    }\n"
        "    return !data_out && lun==0 && (cdb[0]==0x00 || cdb[0]==0x03 ||\n"
        "        cdb[0]==0x12 || cdb[0]==0x25 || cdb[0]==0x28);\n"
        "}\n"
        "static int command(State &s, const uint8_t *cdb, unsigned size, uint32_t len,\n"
        "    uint8_t lun=0, bool data_out=false) {\n"
        "    /* WRITE(10) is accepted only for the validated userdata bounds. */\n"
        "    if (!allowed_cdb(s,cdb,size,len,lun,s.allow_active,data_out)) return EINVAL;",
        "SCSI allowlist and command signature",
    )
    text = replace_once(
        text,
        "    bzero(ucd, sizeof(*ucd));\n"
        "    bzero(buffer(s), bounce_size);\n"
        "    ucd->command[0] = 0x01;\n"
        "    ucd->command[1] = len ? 0x40 : 0;",
        "    bzero(ucd, sizeof(*ucd));\n"
        "    if (!data_out) bzero(buffer(s), bounce_size);\n"
        "    ucd->command[0] = 0x01;\n"
        "    ucd->command[1] = len ? (data_out ? 0x20 : 0x40) : 0;",
        "UPIU direction and bounce initialization",
    )
    text = replace_once(
        text,
        "    trd->words[0] = (1u << 28) | ((len ? 2u : 0u) << 25) | (1u << 24);",
        "    trd->words[0] = (1u << 28) |\n"
        "        ((len ? (data_out ? 1u : 2u) : 0u) << 25) | (1u << 24);",
        "UTRD direction",
    )
    text = replace_once(
        text,
        "    sync(s);\n    write(s, 0x58, 1);",
        "    if (data_out && len) clean_dcache64(s.physical + bounce_offset, len, TRUE);\n"
        "    sync(s);\n    write(s, 0x58, 1);",
        "write DMA cache clean",
    )
    text = replace_once(
        text,
        "static int retry(State &s, const uint8_t *cdb, unsigned size, uint32_t len) {\n"
        "    int error = command(s, cdb, size, len);",
        "static int retry(State &s, const uint8_t *cdb, unsigned size, uint32_t len,\n"
        "    bool data_out=false) {\n"
        "    int error = command(s, cdb, size, len, 0, data_out);",
        "retry direction",
    )
    text = replace_once(
        text,
        "        return command(s,cdb,size,len);",
        "        return command(s,cdb,size,len,0,data_out);",
        "retry after unit attention",
    )
    text = replace_once(
        text,
        "    return error ? error : command(s, cdb, size, len);",
        "    return error ? error : command(s, cdb, size, len, 0, data_out);",
        "retry after request sense",
    )
    text = replace_once(
        text,
        "static int blocks(State &s, uint32_t lba, uint16_t count, uint32_t blocksize) {\n"
        "    if (!count || count > bounce_size/blocksize) return EINVAL;\n"
        "    const uint8_t cdb[10] = {0x28,0,(uint8_t)(lba>>24),(uint8_t)(lba>>16),\n"
        "        (uint8_t)(lba>>8),(uint8_t)lba,0,(uint8_t)(count>>8),(uint8_t)count,0};\n"
        "    return retry(s, cdb, sizeof(cdb), count*blocksize);\n"
        "}\n",
        "static int blocks(State &s, uint32_t lba, uint16_t count, uint32_t blocksize) {\n"
        "    if (!count || !blocksize || count > bounce_size/blocksize) return EINVAL;\n"
        "    const uint8_t cdb[10] = {0x28,0,(uint8_t)(lba>>24),(uint8_t)(lba>>16),\n"
        "        (uint8_t)(lba>>8),(uint8_t)lba,0,(uint8_t)(count>>8),(uint8_t)count,0};\n"
        "    return retry(s, cdb, sizeof(cdb), count*blocksize);\n"
        "}\n"
        "static int write_blocks(State &s, uint64_t lba, uint32_t count) {\n"
        "    if (!s.write_enabled || !s.write_sector_bytes || !count || count>0xffff ||\n"
        "        count>bounce_size/s.write_sector_bytes || lba>UINT32_MAX ||\n"
        "        lba<s.write_first_lba || lba-s.write_first_lba>=s.write_block_count ||\n"
        "        count>s.write_block_count-(lba-s.write_first_lba) ||\n"
        "        (uint64_t)count*s.write_sector_bytes>UINT32_MAX) return EPERM;\n"
        "    const uint8_t cdb[10] = {0x2a,0,(uint8_t)(lba>>24),(uint8_t)(lba>>16),\n"
        "        (uint8_t)(lba>>8),(uint8_t)lba,0,(uint8_t)(count>>8),(uint8_t)count,0};\n"
        "    /* Do not retry data-out: REQUEST SENSE reuses the bounce buffer. */\n"
        "    return command(s,cdb,sizeof(cdb),count*s.write_sector_bytes,0,true);\n"
        "}\n"
        "static int sync_cache(State &s) {\n"
        "    if (!s.write_enabled) return 0;\n"
        "    const uint8_t cdb[10]={0x35};\n"
        "    return command(s,cdb,sizeof(cdb),0,0,false);\n"
        "}\n",
        "bounded WRITE(10) and cache sync helpers",
    )
    text = replace_once(
        text,
        "    if (mode==9) {\n"
        "        marble_block_setup(s,sector,found_first,found_count,(uint64_t)last+1);",
        "    if (mode==9) {\n"
        "        unsigned int write_requested=0;\n"
        "        s.write_enabled=PE_parse_boot_argn(\"marble_ufs_write\",\n"
        "            &write_requested,sizeof(write_requested)) && write_requested==1;\n"
        "        s.write_sector_bytes=sector;\n"
        "        s.write_first_lba=found_first;\n"
        "        s.write_block_count=found_count;\n"
        "        kprintf(\"MARBLE UFS WRITE: %s, userdata-only\",\n"
        "            s.write_enabled ? \"explicit opt-in\" : \"disabled\");\n"
        "        marble_block_setup(s,sector,found_first,found_count,(uint64_t)last+1);\n"
        "        unsigned int write_probe=0;\n"
        "        if (PE_parse_boot_argn(\"marble_ufs_write_probe\", &write_probe,\n"
        "            sizeof(write_probe)) && write_probe==1) {\n"
        "            if (!s.write_enabled) panic(\"MARBLE UFS WRITE PROBE: requires marble_ufs_write=1\");\n"
        "            marble_block_write_probe(s);\n"
        "        }",
        "mode-9 explicit write opt-in",
    )
    return text


def transform_block(text: str) -> str:
    text = replace_once(
        text,
        "static int disk_major=-1;\nstatic uint32_t strategy_reads;",
        "static int disk_major=-1;\n"
        "static bool partition_write_enabled;\n"
        "static uint32_t strategy_reads;",
        "block write state",
    )
    text = replace_once(
        text,
        "static int raw_open(dev_t dev,int flags,int type,struct proc *p) {\n"
        "    return major(dev)==raw_major ? open_disk(block_device(dev),flags,type,p) : ENXIO;\n"
        "}",
        "static int raw_open(dev_t dev,int flags,int type,struct proc *p) {\n"
        "    if (major(dev)!=raw_major) return ENXIO;\n"
        "    if (flags&FWRITE) return EROFS;\n"
        "    return open_disk(block_device(dev),flags,type,p);\n"
        "}",
        "raw node always read-only",
    )
    text = replace_once(
        text,
        "static int raw_ioctl(dev_t dev,u_long cmd,caddr_t data,int flags,struct proc *p) {\n"
        "    return ioctl_disk(block_device(dev),cmd,data,flags,p);\n"
        "}",
        "static int raw_ioctl(dev_t dev,u_long cmd,caddr_t data,int flags,struct proc *p) {\n"
        "    if (major(dev)!=raw_major) return ENXIO;\n"
        "    if (cmd==DKIOCISWRITABLE) { *(uint32_t *)data=0; return 0; }\n"
        "    if (cmd==DKIOCGETMAXBLOCKCOUNTWRITE) { *(uint64_t *)data=0; return 0; }\n"
        "    return ioctl_disk(block_device(dev),cmd,data,flags,p);\n"
        "}",
        "raw ioctl reports readonly",
    )
    text = replace_once(
        text,
        "    return flags&FWRITE ? EROFS : 0;",
        "    return (flags&FWRITE) && (minor(dev)!=1 || !partition_write_enabled) ? EROFS : 0;",
        "partition-only open guard",
    )
    text = replace_once(
        text,
        "    case DKIOCISWRITABLE: *(uint32_t *)data=0; return 0;\n"
        "    case DKIOCGETMAXBLOCKCOUNTREAD: *(uint64_t *)data=bounce_size/512; return 0;\n"
        "    case DKIOCGETMAXBLOCKCOUNTWRITE: *(uint64_t *)data=0; return 0;",
        "    case DKIOCISWRITABLE:\n"
        "        *(uint32_t *)data=(minor(dev)==1 && partition_write_enabled); return 0;\n"
        "    case DKIOCGETMAXBLOCKCOUNTREAD: *(uint64_t *)data=bounce_size/512; return 0;\n"
        "    case DKIOCGETMAXBLOCKCOUNTWRITE:\n"
        "        *(uint64_t *)data=(minor(dev)==1 && partition_write_enabled) ? bounce_size/512 : 0;\n"
        "        return 0;\n"
        "    case DKIOCSYNCHRONIZE:\n"
        "    case DKIOCSYNCHRONIZECACHE:\n"
        "        if (minor(dev)!=1 || !partition_write_enabled) return 0;\n"
        "        lck_mtx_lock(&io_lock);\n"
        "        { int error=sync_cache(*host); lck_mtx_unlock(&io_lock); return error; }",
        "writable ioctls and cache synchronization",
    )
    text = replace_once(
        text,
        "    if (!valid_device(dev)) error=ENXIO;\n"
        "    else if (!(buf_flags(bp)&B_READ)) error=EROFS;\n"
        "    else if (!io_range(buf_blkno(bp),count,",
        "    const bool read_request=(buf_flags(bp)&B_READ)!=0;\n"
        "    if (!valid_device(dev)) error=ENXIO;\n"
        "    else if (!read_request && (minor(dev)!=1 || !partition_write_enabled)) error=EROFS;\n"
        "    else if (!io_range(buf_blkno(bp),count,",
        "partition-only strategy guard",
    )
    text = replace_once(
        text,
        "        error=blocks(*host,(uint32_t)lba,(uint16_t)n,sector_bytes);\n"
        "        if (error) break;\n"
        "        memcpy(address+done,buffer(*host)+skip,want);",
        "        if (read_request) {\n"
        "            error=blocks(*host,(uint32_t)lba,(uint16_t)n,sector_bytes);\n"
        "            if (!error) memcpy(address+done,buffer(*host)+skip,want);\n"
        "        } else {\n"
        "            /* Preserve untouched bytes on unaligned 4 KiB UFS blocks. */\n"
        "            if (skip || (want % sector_bytes))\n"
        "                error=blocks(*host,(uint32_t)lba,(uint16_t)n,sector_bytes);\n"
        "            if (!error) {\n"
        "                memcpy(buffer(*host)+skip,address+done,want);\n"
        "                error=write_blocks(*host,lba,n);\n"
        "            }\n"
        "        }\n"
        "        if (error) break;",
        "bounded read-modify-write strategy",
    )
    text = replace_once(
        text,
        "    marble_block::host=&s; sector_bytes=sector; first_lba=first; part_blocks=count; disk_blocks=total;",
        "    marble_block::host=&s; sector_bytes=sector; first_lba=first; part_blocks=count; disk_blocks=total;\n"
        "    partition_write_enabled=s.write_enabled;",
        "write gate set only after GPT validation",
    )
    text = replace_once(
        text,
        "static void marble_block_setup(marble_scsi::State &s,uint32_t sector,",
        "static void marble_block_write_probe(marble_scsi::State &s) {\n"
        "    using namespace marble_scsi;\n"
        "    using namespace marble_block;\n"
        "    uint8_t before[4096];\n"
        "    if (!partition_write_enabled || sector_bytes>sizeof(before) ||\n"
        "        sector_bytes!=s.write_sector_bytes || !part_blocks ||\n"
        "        first_lba+part_blocks-1>UINT32_MAX) fail(s,23,EPERM);\n"
        "    const uint32_t lba=(uint32_t)(first_lba+part_blocks-1);\n"
        "    lck_mtx_lock(&io_lock);\n"
        "    int error=blocks(s,lba,1,sector_bytes);\n"
        "    if (!error) memcpy(before,buffer(s),sector_bytes);\n"
        "    if (!error) error=write_blocks(s,lba,1);\n"
        "    if (!error) error=sync_cache(s);\n"
        "    if (!error) error=blocks(s,lba,1,sector_bytes);\n"
        "    if (!error && memcmp(before,buffer(s),sector_bytes)) error=EIO;\n"
        "    lck_mtx_unlock(&io_lock);\n"
        "    if (error) fail(s,24,error);\n"
        "    panic(\"MARBLE UFS SAME DATA WRITE OK LBA=%llx\",(uint64_t)lba);\n"
        "}\n"
        "\n"
        "static void marble_block_setup(marble_scsi::State &s,uint32_t sector,",
        "one-sector same-data write probe",
    )
    return text


def transform_probe(text: str) -> str:
    return replace_once(
        text,
        'extern "C" uint64_t marble_ufs_root_read_count(void) {\n'
        "    return marble_block::strategy_reads;\n"
        "}",
        'extern "C" uint64_t marble_ufs_root_read_count(void) {\n'
        "    return marble_block::strategy_reads;\n"
        "}\n"
        'extern "C" int marble_ufs_root_write_enabled(void) {\n'
        "    return marble_block::host != nullptr && marble_block::disk_major >= 0 &&\n"
        "        marble_block::partition_write_enabled ? 1 : 0;\n"
        "}",
        "C root-write capability export",
    )


def host_guard_checks() -> None:
    """Small independent boundary oracle matching strategy and SCSI guards."""
    first, blocks, device_limit = 0x1800000, 0x7000000, 0x10000000
    sector, max_bytes = 4096, 32768

    def strategy_allowed(enabled: bool, minor: int, lba: int, count: int) -> bool:
        return (enabled and minor == 1 and count > 0 and lba <= 0xFFFFFFFF
                and lba >= first and lba - first < blocks
                and count <= blocks - (lba - first)
                and count - 1 <= 0xFFFFFFFF - lba
                and lba + count <= device_limit)

    def cdb_allowed(enabled: bool, lun: int, lba: int, count: int, length: int) -> bool:
        return (enabled and lun == 0 and count > 0 and lba <= 0xFFFFFFFF
                and lba >= first and lba - first < blocks
                and count <= blocks - (lba - first)
                and count - 1 <= 0xFFFFFFFF - lba
                and count <= max_bytes // sector and length == count * sector)

    cases = [
        (True, 1, first, 1, True),
        (True, 1, first + blocks - 1, 1, True),
        (True, 1, first + blocks - 1, 2, False),
        (True, 1, first - 1, 1, False),
        (True, 1, first + blocks + 1, 1, False),
        (True, 0, first, 1, False),
        (False, 1, first, 1, False),
        (True, 1, first, 0, False),
        (True, 1, 0x100000000, 1, False),
    ]
    for enabled, minor, lba, count, expected in cases:
        actual = strategy_allowed(enabled, minor, lba, count)
        if actual != expected:
            raise AssertionError((enabled, minor, lba, count, expected, actual))
    if not cdb_allowed(True, 0, first, 1, sector):
        raise AssertionError("valid bounded WRITE(10) rejected")
    if cdb_allowed(True, 1, first, 1, sector):
        raise AssertionError("nonzero LUN accepted")
    if cdb_allowed(True, 0, first + blocks - 1, 2, 2 * sector):
        raise AssertionError("WRITE(10) crossing userdata end accepted")
    if cdb_allowed(True, 0, first, 9, 9 * sector):
        raise AssertionError("oversized bounce-buffer transfer accepted")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true",
                        help="write the prepared patch into the Mac XNU checkout")
    args = parser.parse_args()
    host_guard_checks()
    if not SCsi.exists() or not BLOCK.exists() or not PROBE.exists():
        raise SystemExit(f"missing source files under {ROOT}; no changes made")
    old_scsi, old_block, old_probe = SCsi.read_text(), BLOCK.read_text(), PROBE.read_text()
    new_scsi, new_block = transform_scsi(old_scsi), transform_block(old_block)
    new_probe = transform_probe(old_probe)
    required = [
        ('"marble_ufs_write"', new_scsi),
        ('cdb[0]==0x2a', new_scsi),
        ('cdb[0]==0x35', new_scsi),
        ('minor(dev)!=1 || !partition_write_enabled', new_block),
        ('write_blocks(*host,lba,n)', new_block),
        ('DKIOCSYNCHRONIZECACHE', new_block),
        ('marble_ufs_root_write_enabled', new_probe),
        ('marble_ufs_write_probe', new_scsi),
        ('SAME DATA WRITE OK', new_block),
        ('count-1>UINT32_MAX-lba', new_scsi),
    ]
    for needle, result in required:
        if needle not in result:
            raise AssertionError(f"prepared source missing {needle}")
    print("PASS: host boundary cases; WRITE(10) opt-in and GPT bounds are present")
    print("PASS: block strategy restricts writes to minor 1 and cache sync is gated")
    print("PASS: separate same-data write probe requires both explicit boot arguments")
    print("Prepared only; the phone has not been touched.")
    if not args.apply:
        print("Dry run. Add --apply on the Mac to create backups and update XNU source.")
        return
    backup = ROOT / "trace-backups" / datetime.now().strftime("%Y%m%d-ufs-partition-write-%H%M%S")
    backup.mkdir(parents=True, exist_ok=False)
    (backup / SCsi.name).write_text(old_scsi)
    (backup / BLOCK.name).write_text(old_block)
    (backup / PROBE.name).write_text(old_probe)
    SCsi.write_text(new_scsi)
    BLOCK.write_text(new_block)
    PROBE.write_text(new_probe)
    report = {
        "change": "opt-in SCSI WRITE(10) to the validated userdata GPT partition only",
        "boot_arg": "marble_ufs_write=1",
        "write_probe_boot_arg": "marble_ufs_write_probe=1 (also requires marble_ufs_write=1)",
        "capability_export": "marble_ufs_root_write_enabled() returns 1 only after mode-9 GPT validation, opt-in and BSD setup",
        "default": "read-only; all other LUNs/CDBs rejected",
        "raw_character_writes": "EROFS",
        "block_minor_0": "read-only whole-LUN device",
        "block_minor_1": "selected userdata partition, writable only with opt-in",
        "backup": str(backup),
        "phone_booted": False,
        "phone_storage_written": False,
        "hardware_write_tested": False,
    }
    (backup / "manifest.json").write_text(json.dumps(report, indent=2) + "\n")
    print(f"Applied to source only; backups: {backup}")


if __name__ == "__main__":
    main()
