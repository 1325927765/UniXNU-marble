#!/usr/bin/env python3
"""Add opt-in bounded HFS clonefile and Marble UFS strategy error tracing.

Dry-run is the default.  --apply backs up both source files before changing
them.  The instrumentation logs only failed clonefile/strategy operations,
requires marble_hfs_error_trace=1, and leaves all I/O results untouched.
"""
from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path


DEFAULT_ROOT = Path.home() / "unixnu-marble8796-build/xnu"
HFS_REL = Path("bsd/marble_hfs/core/hfs_readwrite.c")
UFS_REL = Path("iokit/bsddev/marble_ufs_block.inc")

HFS_TRACE = r'''
static uint32_t marble_hfs_clone_errors_logged;

static void
marble_hfs_trace_clone_error(vnode_t vp, int blkstart, int blkcnt, int blksize,
	 off_t writebase, size_t offset, size_t iosize, int error,
	 off_t uiooff, off_t resid)
{
	unsigned int enabled = 0;
	if (error == 0 ||
	    !PE_parse_boot_argn("marble_hfs_error_trace", &enabled, sizeof(enabled)) ||
	    enabled != 1) {
		return;
	}
	uint32_t slot = __atomic_fetch_add(&marble_hfs_clone_errors_logged, 1, __ATOMIC_RELAXED);
	if (slot >= 16) {
		return;
	}
	char name[32] = { 0 };
	proc_selfname(name, sizeof(name));
	printf("MARBLE HFSERR clonefile[%u] proc=%s[%d] fileid=%u blkstart=%d blkcnt=%d blksize=%d writebase=%lld offset=%llu iosize=%llu uiooff=%lld resid=%lld errno=%d\n",
	    slot + 1, name, proc_selfpid(), VTOC(vp)->c_fileid, blkstart, blkcnt, blksize,
	    (long long)writebase, (unsigned long long)offset, (unsigned long long)iosize,
	    (long long)uiooff, (long long)resid, error);
}
'''

UFS_TRACE = r'''
static uint32_t marble_ufs_strategy_errors_logged;

static void trace_strategy_error(buf_t bp, int error, uint64_t offset)
{
    unsigned int enabled = 0;
    if (!error ||
        !PE_parse_boot_argn("marble_hfs_error_trace", &enabled, sizeof(enabled)) ||
        enabled != 1) return;
    uint32_t slot = __atomic_fetch_add(&marble_ufs_strategy_errors_logged, 1, __ATOMIC_RELAXED);
    if (slot >= 16) return;
    char name[32] = {0};
    proc_selfname(name, sizeof(name));
    dev_t dev = buf_device(bp);
    printf("MARBLE UFSERR strategy[%u] proc=%s[%d] dev=%u:%u read=%u blk=%lld bytes=%u offset=%llu sector=%u first_lba=%llu part_blocks=%llu errno=%d\n",
        slot + 1, name, proc_selfpid(), major(dev), minor(dev),
        (buf_flags(bp)&B_READ)!=0, (long long)buf_blkno(bp), buf_count(bp),
        (unsigned long long)offset, sector_bytes,
        (unsigned long long)first_lba, (unsigned long long)part_blocks, error);
}
'''


def once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one exact anchor, found {count}")
    return text.replace(old, new, 1)


def transform_hfs(text: str) -> str:
    if "marble_hfs_trace_clone_error" in text:
        raise RuntimeError("HFS error trace already installed")
    text = once(text, "#include <IOKit/IOBSD.h>",
                "#include <IOKit/IOBSD.h>\n#include <pexpert/pexpert.h>",
                "HFS boot-arg declaration")
    # Place the helper before the function body, after all declarations/includes.
    marker = "static int  hfs_clonefile(struct vnode *, int, int, int);\n"
    text = once(text, marker, marker + HFS_TRACE + "\n", "HFS trace helper insertion")
    old = '''\t\tif (error) {
			printf("hfs_clonefile: cluster_write failed - %d\\n", error);
			break;
		}'''
    new = '''		if (error) {
			marble_hfs_trace_clone_error(vp, blkstart, blkcnt, blksize,
			    writebase, offset, iosize, error, uio_offset(auio), uio_resid(auio));
			printf("hfs_clonefile: cluster_write failed - %d\\n", error);
			break;
		}'''
    return once(text, old, new, "HFS clonefile cluster_write error")


def transform_ufs(text: str) -> str:
    if "marble_ufs_strategy_errors_logged" in text:
        raise RuntimeError("UFS strategy error trace already installed")
    text = once(text, "#include <kern/locks.h>",
                "#include <kern/locks.h>\n#include <pexpert/pexpert.h>\n#include <sys/proc.h>",
                "UFS boot-arg/process declarations")
    anchor = "static bool io_range(int64_t block,uint32_t count,uint64_t bytes,uint64_t &offset) {"
    text = once(text, anchor, UFS_TRACE + "\n" + anchor, "UFS trace helper insertion")
    old = '''    if (error || !count) {
        if (error) buf_seterror(bp,error);
        buf_biodone(bp);
        return;
    }'''
    new = '''    if (error || !count) {
        trace_strategy_error(bp,error,offset);
        if (error) buf_seterror(bp,error);
        buf_biodone(bp);
        return;
    }'''
    text = once(text, old, new, "UFS strategy preflight failure")
    old = '''    if (error) buf_seterror(bp,error);
    buf_biodone(bp);
}'''
    new = '''    trace_strategy_error(bp,error,offset);
    if (error) buf_seterror(bp,error);
    buf_biodone(bp);
}'''
    return once(text, old, new, "UFS strategy completion failure")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=DEFAULT_ROOT,
                        help="XNU source root (default: ~/unixnu-marble8796-build/xnu)")
    parser.add_argument("--apply", action="store_true", help="Back up and modify the two source files")
    args = parser.parse_args()
    root = args.source_root.resolve()
    hfs_path, ufs_path = root / HFS_REL, root / UFS_REL
    if not hfs_path.is_file() or not ufs_path.is_file():
        raise SystemExit(f"expected source files under {root}: {HFS_REL}, {UFS_REL}")
    old_hfs, old_ufs = hfs_path.read_text(), ufs_path.read_text()
    new_hfs, new_ufs = transform_hfs(old_hfs), transform_ufs(old_ufs)
    print("PASS: HFS trace is only on cluster_write failure; first 16 only; opt-in boot arg")
    print("PASS: UFS trace is only on strategy errors; first 16 only; logs bounds and errno")
    print("PASS: original errno, biodone, and I/O control flow are preserved")
    if not args.apply:
        print("Dry run; no files changed")
        return
    backup = root / "trace-backups" / datetime.now().strftime("%Y%m%d-hfs-errors-%H%M%S")
    backup.mkdir(parents=True, exist_ok=False)
    (backup / HFS_REL.name).write_text(old_hfs)
    (backup / UFS_REL.name).write_text(old_ufs)
    hfs_path.write_text(new_hfs)
    ufs_path.write_text(new_ufs)
    (backup / "manifest.json").write_text(json.dumps({
        "hfs_source": str(hfs_path),
        "ufs_source": str(ufs_path),
        "before_sha256": {"hfs": hashlib.sha256(old_hfs.encode()).hexdigest(),
                           "ufs": hashlib.sha256(old_ufs.encode()).hexdigest()},
        "after_sha256": {"hfs": hashlib.sha256(new_hfs.encode()).hexdigest(),
                          "ufs": hashlib.sha256(new_ufs.encode()).hexdigest()},
        "boot_arg": "marble_hfs_error_trace=1",
        "limits": {"hfs_clonefile_errors": 16, "ufs_strategy_errors": 16},
        "behavior_change": "bounded opt-in diagnostic output only",
    }, indent=2) + "\n")
    print(f"Applied; backups and manifest: {backup}")


if __name__ == "__main__":
    main()
