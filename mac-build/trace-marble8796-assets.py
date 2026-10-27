#!/usr/bin/env python3
"""Generate an opt-in, bounded Marble asset/cache audit in bsd_init.c.

Dry-run is the default. --apply backs up the target source before modifying it.
The diagnostic only opens files read-only, reports sizes and CRC32 prefixes,
and never changes filesystem state or boot policy.
"""
from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path


DEFAULT_ROOT = Path.home() / "unixnu-marble8796-build/xnu"
REL = Path("bsd/kern/bsd_init.c")

TRACE = r'''
#if defined(ARM64_BOARD_CONFIG_MARBLE)
#include <sys/fcntl.h>
/* Opt-in early-boot asset audit. Static scratch keeps the kernel stack bounded. */
#define MARBLE_ASSET_AUDIT_MAX (256U * 1024U)
#define MARBLE_ASSET_AUDIT_CHUNK 4096U
static char marble_asset_audit_scratch[MARBLE_ASSET_AUDIT_CHUNK];

static uint32_t
marble_asset_audit_crc32(const uint8_t *bytes, size_t length, uint32_t crc)
{
	for (size_t i = 0; i < length; i++) {
		crc ^= bytes[i];
		for (unsigned int bit = 0; bit < 8; bit++) {
			crc = (crc >> 1) ^ ((crc & 1) ? 0xedb88320U : 0U);
		}
	}
	return crc;
}

static void
marble_asset_audit_file(const char *path, proc_t p, vfs_context_t ctx, bool crc_prefix)
{
	vnode_t vp = NULL;
	struct vnode_attr va;
	int error;
	uint64_t size = 0;
	size_t limit = 0, done = 0;
	uint32_t crc = 0xffffffffU;
	bool have_size = false;

	error = vnode_open(path, FREAD, 0, 0, &vp, ctx);
	if (error != 0) {
		printf("MARBLE ASSET: path=%s open_errno=%d\n", path, error);
		return;
	}

	VATTR_INIT(&va);
	VATTR_WANTED(&va, va_data_size);
	error = vnode_getattr(vp, &va, ctx);
	if (error == 0 && VATTR_IS_SUPPORTED(&va, va_data_size)) {
		size = va.va_data_size;
		have_size = true;
	}
	if (!crc_prefix || !have_size || size == 0) {
		printf("MARBLE ASSET: path=%s getattr_errno=%d size=%s%llu\n",
		    path, error, have_size ? "" : "unknown/", (unsigned long long)size);
		(void)vnode_close(vp, FREAD, ctx);
		return;
	}

	limit = (size > MARBLE_ASSET_AUDIT_MAX) ? MARBLE_ASSET_AUDIT_MAX : (size_t)size;
	while (done < limit) {
		size_t want = limit - done;
		int resid = 0;
		if (want > sizeof(marble_asset_audit_scratch)) {
			want = sizeof(marble_asset_audit_scratch);
		}
		error = vn_rdwr(UIO_READ, vp, marble_asset_audit_scratch, (int)want,
		    (off_t)done, UIO_SYSSPACE, 0, vfs_context_ucred(ctx), &resid, p);
		if (resid < 0 || (size_t)resid > want) {
			error = EIO;
			break;
		}
		size_t got = want - (size_t)resid;
		if (got != 0) {
			crc = marble_asset_audit_crc32((const uint8_t *)marble_asset_audit_scratch, got, crc);
			done += got;
		}
		if (error != 0 || got != want) {
			if (error == 0) {
				error = EIO;
			}
			break;
		}
	}
	crc ^= 0xffffffffU;
	printf("MARBLE ASSET: path=%s size=%llu prefix_bytes=%llu prefix_crc32=%08x read_errno=%d%s\n",
	    path, (unsigned long long)size, (unsigned long long)done, crc, error,
	    size > MARBLE_ASSET_AUDIT_MAX ? " capped=262144" : "");
	(void)vnode_close(vp, FREAD, ctx);
}

static void
marble_asset_audit(proc_t p)
{
	unsigned int enabled = 0;
	if (!PE_parse_boot_argn("marble_asset_audit", &enabled, sizeof(enabled)) || enabled != 1) {
		return;
	}
	vfs_context_t ctx = vfs_context_current();
	printf("MARBLE ASSET: audit start\n");
	marble_asset_audit_file("/System/Library/PrivateFrameworks/UIKitCore.framework/BoundingPathData.bundle/Assets.car", p, ctx, true);
	marble_asset_audit_file("/System/Library/PrivateFrameworks/UIKitCore.framework/BoundingPathData.bundle/Info.plist", p, ctx, true);
	marble_asset_audit_file("/System/Library/PrivateFrameworks/UIKitCore.framework/BoundingPathData.bundle/BoundingPathData", p, ctx, true);
	marble_asset_audit_file("/private/var/containers/Shared/SystemGroup/systemgroup.com.apple.mobilegestaltcache/Library/Caches/com.apple.MobileGestalt.plist", p, ctx, false);
	printf("MARBLE ASSET: audit end\n");
}
#endif /* MARBLE */
'''


def once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one exact anchor, found {count}")
    return text.replace(old, new, 1)


def transform(text: str) -> str:
    if "marble_asset_audit_file" in text:
        raise RuntimeError("asset audit already installed")
    text = once(text, "void\nbsdinit_task(void)\n{", TRACE + "\nvoid\nbsdinit_task(void)\n{",
                "MARBLE audit helper insertion")
    text = once(text, "\tload_init_program(p);",
                "#if defined(ARM64_BOARD_CONFIG_MARBLE)\n\tmarble_asset_audit(p);\n#endif\n\tload_init_program(p);",
                "one-shot call before launchd")
    return text


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=DEFAULT_ROOT,
                        help="XNU source root (default: ~/unixnu-marble8796-build/xnu)")
    parser.add_argument("--apply", action="store_true", help="Back up and modify bsd_init.c")
    args = parser.parse_args()
    root = args.source_root.resolve()
    path = root / REL
    if not path.is_file():
        raise SystemExit(f"expected source file under {root}: {REL}")
    original = path.read_text()
    updated = transform(original)
    print("PASS: code and call are compiled only for MARBLE; runtime requires marble_asset_audit=1")
    print("PASS: opens four fixed paths read-only; CRC reads capped at 256 KiB/file with static 4 KiB scratch")
    print("PASS: vnode_close on every successful open; cache plist reports attributes only")
    print("PASS: call occurs immediately before load_init_program; no policy or filesystem changes")
    if not args.apply:
        print("Dry run; no files changed")
        return
    backup = root / "trace-backups" / datetime.now().strftime("%Y%m%d-assets-audit-%H%M%S")
    backup.mkdir(parents=True, exist_ok=False)
    (backup / REL.name).write_text(original)
    path.write_text(updated)
    (backup / "manifest.json").write_text(json.dumps({
        "source": str(path),
        "before_sha256": hashlib.sha256(original.encode()).hexdigest(),
        "after_sha256": hashlib.sha256(updated.encode()).hexdigest(),
        "boot_arg": "marble_asset_audit=1",
        "files": [
            "/System/Library/PrivateFrameworks/UIKitCore.framework/BoundingPathData.bundle/Assets.car",
            "/System/Library/PrivateFrameworks/UIKitCore.framework/BoundingPathData.bundle/Info.plist",
            "/System/Library/PrivateFrameworks/UIKitCore.framework/BoundingPathData.bundle/BoundingPathData",
            "/private/var/containers/Shared/SystemGroup/systemgroup.com.apple.mobilegestaltcache/Library/Caches/com.apple.MobileGestalt.plist",
        ],
        "limits": {"crc_prefix_bytes_per_file": 262144, "scratch_bytes": 4096},
        "behavior_change": "opt-in read-only diagnostics before launchd",
    }, indent=2) + "\n")
    print(f"Applied; backup and manifest: {backup}")


if __name__ == "__main__":
    main()

