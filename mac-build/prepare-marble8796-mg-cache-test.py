#!/usr/bin/env python3
"""Prepare an opt-in, one-shot MobileGestalt cache rename test for Marble.

Dry-run is the default. --apply backs up both XNU source files before edits.
This is a narrowly scoped hypothesis test: it does not delete, truncate, or
rewrite the cache. The original is retained at a fixed sibling pathname.
"""
from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path


DEFAULT_ROOT = Path.home() / "unixnu-marble8796-build/xnu"
BSD_INIT = Path("bsd/kern/bsd_init.c")
VFS_SYSCALLS = Path("bsd/vfs/vfs_syscalls.c")

MG_TRACE = r'''
#if defined(ARM64_BOARD_CONFIG_MARBLE)
/* One-shot cache hypothesis test; never overwrite an existing backup. */
void
marble_mg_cache_test(void)
{
	static const char source[] = "/private/var/containers/Shared/SystemGroup/systemgroup.com.apple.mobilegestaltcache/Library/Caches/com.apple.MobileGestalt.plist";
	static const char backup[] = "/private/var/containers/Shared/SystemGroup/systemgroup.com.apple.mobilegestaltcache/Library/Caches/com.apple.MobileGestalt.plist.marble-before-iphone-x";
	unsigned int enabled = 0, writable = 0;
	vnode_t vp = NULL;
	struct vnode_attr va;
	vfs_context_t ctx = vfs_context_current();
	int error;

	if (!PE_parse_boot_argn("marble_mg_cache_reset", &enabled, sizeof(enabled)) || enabled != 1) {
		return;
	}
	if (!PE_parse_boot_argn("marble_ufs_write", &writable, sizeof(writable)) || writable != 1) {
		printf("MARBLE MG CACHE: skipped; marble_ufs_write=1 required\n");
		return;
	}
	error = vnode_lookup(source, VNODE_LOOKUP_NOFOLLOW, &vp, ctx);
	if (error != 0) {
		printf("MARBLE MG CACHE: skipped; source lookup errno=%d\n", error);
		return;
	}
	if (!vnode_isreg(vp)) {
		printf("MARBLE MG CACHE: skipped; source is not a regular file\n");
		vnode_put(vp);
		return;
	}
	VATTR_INIT(&va);
	VATTR_WANTED(&va, va_data_size);
	error = vnode_getattr(vp, &va, ctx);
	if (error != 0 || !VATTR_IS_SUPPORTED(&va, va_data_size)) {
		printf("MARBLE MG CACHE: skipped; getattr errno=%d\n", error ? error : EIO);
		vnode_put(vp);
		return;
	}
	uint64_t size = va.va_data_size;
	vnode_put(vp);
	if (size == 0 || size > (1024U * 1024U)) {
		printf("MARBLE MG CACHE: skipped; size=%llu outside 1..1048576\n",
		    (unsigned long long)size);
		return;
	}

	error = renameat_internal(ctx, AT_FDCWD, (user_addr_t)source,
	    AT_FDCWD, (user_addr_t)backup, UIO_SYSSPACE,
	    RENAME_EXCL | RENAME_NOFOLLOW_ANY);
	if (error == EEXIST) {
		printf("MARBLE MG CACHE: skipped; backup already exists errno=%d\n", error);
	} else if (error != 0) {
		printf("MARBLE MG CACHE: rename failed errno=%d source_size=%llu\n",
		    error, (unsigned long long)size);
	} else {
		printf("MARBLE MG CACHE: renamed original to fixed backup; bytes=%llu\n",
		    (unsigned long long)size);
	}
}
#endif /* ARM64_BOARD_CONFIG_MARBLE */
'''


def once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one exact anchor, found {count}")
    return text.replace(old, new, 1)


def transform_vfs(text: str) -> str:
    if "marble_mg_cache_test(void)" in text:
        raise RuntimeError("MobileGestalt cache helper already installed")
    if "#include <pexpert/pexpert.h>" not in text:
        text = once(text, "#include <sys/param.h>",
                    "#include <sys/param.h>\n#include <pexpert/pexpert.h>",
                    "boot-arg parser include")
    marker = "int\nrename(__unused proc_t p, struct rename_args *uap, __unused int32_t *retval)\n{"
    return once(text, marker, MG_TRACE + "\n" + marker,
                "cache test helper insertion before rename syscall")


def transform_init(text: str) -> str:
    if "marble_mg_cache_test();" in text:
        raise RuntimeError("MobileGestalt cache call already installed")
    marker = "void\nbsdinit_task(void)\n{"
    text = once(text, marker,
                "#if defined(ARM64_BOARD_CONFIG_MARBLE)\nextern void marble_mg_cache_test(void);\n#endif\n\n" + marker,
                "Marble helper declaration")
    call = "\tmarble_asset_audit(p);"
    replacement = "#if defined(ARM64_BOARD_CONFIG_MARBLE)\n\tmarble_mg_cache_test();\n#endif\n" + call
    return once(text, call, replacement, "cache test call before asset audit")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=DEFAULT_ROOT,
                        help="XNU source root (default: ~/unixnu-marble8796-build/xnu)")
    parser.add_argument("--apply", action="store_true", help="Back up and modify both source files")
    args = parser.parse_args()
    root = args.source_root.resolve()
    init_path, vfs_path = root / BSD_INIT, root / VFS_SYSCALLS
    if not init_path.is_file() or not vfs_path.is_file():
        raise SystemExit(f"expected {BSD_INIT} and {VFS_SYSCALLS} under {root}")
    old_init, old_vfs = init_path.read_text(), vfs_path.read_text()
    new_init, new_vfs = transform_init(old_init), transform_vfs(old_vfs)
    print("PASS: cache rename code and call are compile-guarded to ARM64_BOARD_CONFIG_MARBLE")
    print("PASS: runtime requires marble_mg_cache_reset=1 AND marble_ufs_write=1")
    print("PASS: exact source path, no-follow regular-file check, size must be 1..1 MiB")
    print("PASS: renameat_internal uses RENAME_EXCL|RENAME_NOFOLLOW_ANY; EEXIST preserves original")
    print("PASS: one-shot call precedes asset audit/load_init_program; no unlink, truncation, or policy change")
    if not args.apply:
        print("Dry run; no files changed")
        return
    backup = root / "trace-backups" / datetime.now().strftime("%Y%m%d-mg-cache-test-%H%M%S")
    backup.mkdir(parents=True, exist_ok=False)
    (backup / BSD_INIT.name).write_text(old_init)
    (backup / VFS_SYSCALLS.name).write_text(old_vfs)
    init_path.write_text(new_init)
    vfs_path.write_text(new_vfs)
    (backup / "manifest.json").write_text(json.dumps({
        "bsd_init": str(init_path),
        "vfs_syscalls": str(vfs_path),
        "before_sha256": {
            "bsd_init": hashlib.sha256(old_init.encode()).hexdigest(),
            "vfs_syscalls": hashlib.sha256(old_vfs.encode()).hexdigest(),
        },
        "after_sha256": {
            "bsd_init": hashlib.sha256(new_init.encode()).hexdigest(),
            "vfs_syscalls": hashlib.sha256(new_vfs.encode()).hexdigest(),
        },
        "boot_args": ["marble_mg_cache_reset=1", "marble_ufs_write=1"],
        "source": "/private/var/containers/Shared/SystemGroup/systemgroup.com.apple.mobilegestaltcache/Library/Caches/com.apple.MobileGestalt.plist",
        "backup": "/private/var/containers/Shared/SystemGroup/systemgroup.com.apple.mobilegestaltcache/Library/Caches/com.apple.MobileGestalt.plist.marble-before-iphone-x",
        "size_bounds": {"minimum_bytes": 1, "maximum_bytes": 1048576},
        "behavior_change": "opt-in one-shot rename preserving original cache at fixed sibling path",
    }, indent=2) + "\n")
    print(f"Applied; backups and manifest: {backup}")


if __name__ == "__main__":
    main()
