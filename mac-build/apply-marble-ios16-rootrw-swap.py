"""Apply the QEMU-only iOS 16 root-write and HFS atomic-swap experiment.

This edits only the prepared Mac XNU source tree. It keeps the normal root
read-only unless marble_qemu_writable_root=1 is present in boot arguments.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import re

root = Path.home() / "unixnu-marble8796-build/xnu"
backup = Path.home() / "unixnu-marble8796-build/trace-backups/20261024-ios16-rootrw-swap-v2"
files = {
    "bsd/vfs/vfs_subr.c": {
        "needle": "mp->mnt_flag = MNT_RDONLY | MNT_ROOTFS;",
        "replacement": (
            "mp->mnt_flag = MNT_RDONLY | MNT_ROOTFS;\n"
            "#if defined(ARM64_BOARD_CONFIG_MARBLE)\n"
            "\t\t/* QEMU disposable-image experiment only; default stays sealed. */\n"
            "\t\t{\n"
            "\t\t\tuint32_t marble_qemu_writable_root = 0;\n"
            "\t\t\tif (PE_parse_boot_argn(\"marble_qemu_writable_root\",\n"
            "\t\t\t    &marble_qemu_writable_root, sizeof(marble_qemu_writable_root)) &&\n"
            "\t\t\t    marble_qemu_writable_root == 1) {\n"
            "\t\t\t\tmp->mnt_flag &= ~MNT_RDONLY;\n"
            "\t\t\t\tprintf(\"MARBLE QEMU ROOT: writable test requested\\n\");\n"
            "\t\t\t}\n"
            "\t\t}\n"
            "#endif\n"
        ),
        "include": "#include <pexpert/pexpert.h>\n",
        "include_after": "#include <sys/param.h>\n",
    },
    "bsd/kern/marble_amfi.c": {
        "needle": "if (mp != NULL && (vfs_flags(mp) & (MNT_ROOTFS | MNT_RDONLY)) == (MNT_ROOTFS | MNT_RDONLY) && marble_ios16_hash_allowed(cs_blob)) {",
        "replacement": (
            "        uint32_t marble_qemu_writable_root = 0;\n"
            "        int root_is_readonly = mp != NULL && (vfs_flags(mp) & MNT_RDONLY);\n"
            "        int qemu_rootrw = PE_parse_boot_argn(\"marble_qemu_writable_root\",\n"
            "            &marble_qemu_writable_root, sizeof(marble_qemu_writable_root)) &&\n"
            "            marble_qemu_writable_root == 1;\n"
            "        if (mp != NULL && (vfs_flags(mp) & MNT_ROOTFS) &&\n"
            "            (root_is_readonly || qemu_rootrw) && marble_ios16_hash_allowed(cs_blob)) {"
        ),
        "include": "#include <pexpert/pexpert.h>\n",
        "include_after": "#include <kern/startup.h>\n",
    },
    "bsd/vfs/kpi_vfs.c": {
        "needle": "If moved to a new directory that is restricted,",
        "replacement": (
            "#if defined(ARM64_BOARD_CONFIG_MARBLE)\n"
            "\t\t/* Match HFS exchangedata for atomic same-volume file swaps, only in QEMU test mode. */\n"
            "\t\tif (_err == ENOTSUP && flags == VFS_RENAME_SWAP && *tvpp != NULLVP &&\n"
            "\t\t    vnode_isreg(*fvpp) && vnode_isreg(*tvpp) &&\n"
            "\t\t    vnode_mount(*fvpp) == vnode_mount(*tvpp)) {\n"
            "\t\t\tuint32_t marble_qemu_writable_root = 0;\n"
            "\t\t\tif (PE_parse_boot_argn(\"marble_qemu_writable_root\",\n"
            "\t\t\t    &marble_qemu_writable_root, sizeof(marble_qemu_writable_root)) &&\n"
            "\t\t\t    marble_qemu_writable_root == 1)\n"
            "\t\t\t\t_err = VNOP_EXCHANGE(*fvpp, *tvpp, 0, ctx);\n"
            "\t\t}\n"
            "#endif\n\n"
            "\t\t/*\n\t\t * If moved to a new directory that is restricted,"
        ),
        "include": "#include <pexpert/pexpert.h>\n",
        "include_after": "#include <sys/param.h>\n",
    },
}

if not root.is_dir():
    raise SystemExit(f"prepared XNU source tree is missing: {root}")
if backup.exists():
    raise SystemExit(f"refusing to overwrite existing backup: {backup}")
originals = {}
for rel, spec in files.items():
    text = (root / rel).read_text()
    if text.count(spec["needle"]) != 1:
        raise SystemExit(f"expected one exact patch point in {rel}")
    if text.count(spec["include"]) != 0:
        raise SystemExit(f"include already exists in {rel}; inspect source before applying")
    originals[rel] = text
backup.mkdir(parents=True)
report = {"source": str(root), "backup": str(backup), "files": {}}
for rel, spec in files.items():
    path = root / rel
    text = originals[rel]
    shutil.copy2(path, backup / Path(rel).name)
    if rel.endswith("vfs_subr.c"):
        updated, count = re.subn(r"(?m)^(\s*)mp->mnt_flag = MNT_RDONLY \| MNT_ROOTFS;\s*$",
                                 lambda m: m.group(1) + spec["replacement"], text, count=1)
        if count != 1:
            raise SystemExit("failed to replace root mount flag line")
    elif rel.endswith("kpi_vfs.c"):
        marker = "If moved to a new directory that is restricted,"
        comment = text.rfind("/*", 0, text.index(marker))
        updated = text[:comment] + spec["replacement"].replace(
            "\t\t/*\n\t\t * If moved to a new directory that is restricted,", "") + text[comment:]
    else:
        if rel.endswith("marble_amfi.c"):
            pos = text.index(spec["needle"])
            line_start = text.rfind("\n", 0, pos) + 1
            indent = text[line_start:pos]
            replacement = spec["replacement"].replace("        ", indent)
            updated = text[:line_start] + replacement + text[pos + len(spec["needle"]):]
        else:
            updated = text.replace(spec["needle"], spec["replacement"], 1)
    include_after = spec["include_after"]
    if updated.count(include_after) != 1:
        raise SystemExit(f"expected one include anchor in {rel}")
    updated = updated.replace(include_after, include_after + spec["include"], 1)
    path.write_text(updated)
    report["files"][rel] = {
        "backup": str(backup / Path(rel).name),
        "sha256": hashlib.sha256(updated.encode()).hexdigest(),
    }
(backup / "manifest.json").write_text(json.dumps(report, indent=2) + "\n")
print(json.dumps(report, indent=2))
