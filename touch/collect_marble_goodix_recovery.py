#!/usr/bin/env python3
"""Read-only, target-serial ADB collection for POCO F5 Goodix touch evidence.

Only runs adb shell reads and adb pull to a host output directory. It never
mounts partitions, changes permissions, loads modules, writes sysfs, reboots,
or sends controller/SPI commands. Vendor-boot block copying is separately
opt-in and requires an explicit block path.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys


PROPS = ("ro.product.device", "ro.build.product", "ro.product.vendor.device",
         "ro.product.model", "ro.boot.product.hardware.sku")
FIRMWARE = ("goodix_firmware_TM.bin", "goodix_cfg_group_TM.bin",
            "goodix_firmware_TM_Second.bin", "goodix_cfg_group_TM_Second.bin")
MODULE_BASES = ("goodix_core.ko", "goodix_9916r.ko", "goodix_9916.ko", "goodix_brl_spi.ko",
                "goodix_ts_core.ko", "goodix.ko")
MODULES = tuple(name + suffix for name in MODULE_BASES for suffix in ("", ".xz", ".gz"))
SEARCH_DIRS = ("/vendor", "/vendor_dlkm", "/odm", "/system/vendor", "/system/vendor_dlkm",
               "/vendor_firmware_mnt")


def adb(serial: str, *args: str, check: bool = True, timeout: int = 45) -> subprocess.CompletedProcess:
    proc = subprocess.run(["adb", "-s", serial, *args], capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=timeout)
    if check and proc.returncode:
        raise RuntimeError(f"adb {args!r} failed ({proc.returncode}): {proc.stderr.strip()}")
    return proc


def remote_read(serial: str, command: str) -> str:
    return adb(serial, "shell", command).stdout.strip()


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def vendor_boot_copy(serial: str, block: str, output: Path, max_bytes: int) -> dict:
    if not re.fullmatch(r"/dev/block/[A-Za-z0-9_./+-]+", block) or ".." in block.split("/"):
        raise SystemExit("--vendor-boot-block must be a literal /dev/block path without '..'")
    # adb exec-out streams dd's stdout directly to a host file. No remote output
    # path is given, and the command has no output target (therefore no writes).
    command = ["adb", "-s", serial, "exec-out", "dd", f"if={block}", "bs=1048576"]
    proc = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    copied = 0
    try:
        with output.open("wb") as dest:
            assert proc.stdout is not None
            while True:
                chunk = proc.stdout.read(1024 * 1024)
                if not chunk:
                    break
                copied += len(chunk)
                if copied > max_bytes:
                    proc.kill()
                    raise RuntimeError(f"partition stream exceeded configured cap ({max_bytes} bytes)")
                dest.write(chunk)
    except Exception:
        proc.kill()
        output.unlink(missing_ok=True)
        raise
    stderr = proc.stderr.read().decode("utf-8", "replace") if proc.stderr else ""
    rc = proc.wait(timeout=20)
    if rc != 0:
        output.unlink(missing_ok=True)
        raise RuntimeError(f"read-only vendor_boot dd failed ({rc}): {stderr.strip()}")
    return {"host_file": str(output), "size_bytes": copied, "sha256": sha256(output),
            "source_block": block, "method": "adb exec-out dd if=... to host stdout only"}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--serial", required=True, help="explicit adb serial from `adb devices`")
    ap.add_argument("--out", type=Path, required=True, help="host directory for small pulled evidence")
    ap.add_argument("--pull-vendor-boot", action="store_true",
                    help="explicitly stream one named vendor_boot block to host (read-only)")
    ap.add_argument("--vendor-boot-block", help="required with --pull-vendor-boot, e.g. /dev/block/by-name/vendor_boot")
    ap.add_argument("--vendor-boot-max-mib", type=int, default=512)
    args = ap.parse_args()
    if args.pull_vendor_boot != bool(args.vendor_boot_block):
        ap.error("--pull-vendor-boot and --vendor-boot-block must be supplied together")
    if not 1 <= args.vendor_boot_max_mib <= 1024:
        ap.error("--vendor-boot-max-mib must be between 1 and 1024")

    state = adb(args.serial, "get-state").stdout.strip()
    if state not in ("device", "recovery"):
        raise SystemExit(f"ADB target {args.serial} is {state!r}, expected 'device' or 'recovery'")
    props = {key: remote_read(args.serial, f"getprop {key}") for key in PROPS}
    product_values = {props[key].strip().lower() for key in
                      ("ro.product.device", "ro.build.product", "ro.product.vendor.device")
                      if props[key].strip().lower() not in ("", "unknown")}
    if product_values and not all(v == "marble" or v.startswith("marblein") for v in product_values):
        raise SystemExit(f"ADB properties do not identify marble/marblein; refusing collection: {props}")

    args.out.mkdir(parents=True, exist_ok=True)
    evidence: dict = {"serial": args.serial, "adb_state": state, "properties": props,
                      "product_verified": bool(product_values), "vendor_mounts": {},
                      "found_remote_files": [], "pulled_host_files": [], "vendor_boot": None,
                      "actions": "read-only adb shell, bounded adb pull, optional explicit dd-to-host only"}
    mounts = {}
    for directory in SEARCH_DIRS:
        mounts[directory] = remote_read(args.serial, f"if [ -d {directory} ]; then echo mounted_or_present; else echo absent; fi")
    evidence["vendor_mounts"] = mounts

    # Search only named vendor trees and exact artifact basenames; do not mount.
    name_terms = " -o ".join(f"-name {name}" for name in (*FIRMWARE, *MODULES))
    paths = " ".join(SEARCH_DIRS)
    find_cmd = f"for d in {paths}; do [ -d \"$d\" ] && find \"$d\" -type f \\( {name_terms} \\) -print 2>/dev/null; done; true"
    result = remote_read(args.serial, find_cmd)
    remote_files = sorted(set(line.strip() for line in result.splitlines() if line.strip().startswith("/")))
    evidence["found_remote_files"] = remote_files
    module_metadata = []
    for index, remote in enumerate(remote_files):
        local_name = f"{index:02d}-{Path(remote).name}"
        dest = args.out / local_name
        pulled = adb(args.serial, "pull", remote, str(dest), check=False, timeout=90)
        if pulled.returncode:
            evidence["pulled_host_files"].append({"remote": remote, "error": pulled.stderr.strip()})
            continue
        evidence["pulled_host_files"].append({"remote": remote, "host_file": str(dest),
                                               "size_bytes": dest.stat().st_size, "sha256": sha256(dest)})
        if dest.name.endswith(".ko"):
            raw = dest.read_bytes()
            strings = [part.decode("ascii", "replace") for part in raw.split(b"\0") if part]
            markers = [s for s in strings if (s.startswith(("vermagic=", "license=", "author=", "alias="))
                                                or s == "goodix,9916r-spi"
                                                or s.startswith("v1.2.")
                                                or (s.startswith("goodix_") and ("TM" in s or "Second" in s)))]
            module_metadata.append({"remote": remote, "metadata_markers": markers})
    evidence["module_metadata"] = module_metadata

    evidence["proc_modules"] = remote_read(args.serial, "cat /proc/modules 2>/dev/null || true")
    sysfs = (
        "for d in /sys/bus/spi/devices/*; do [ -e \"$d\" ] || continue; "
        "echo DEVICE:$d; cat \"$d/modalias\" 2>/dev/null; "
        "readlink -f \"$d/driver\" 2>/dev/null; done; "
        "for d in /sys/class/input/input*; do [ -e \"$d\" ] || continue; "
        "echo INPUT:$d; cat \"$d/name\" 2>/dev/null; done"
    )
    evidence["sysfs_spi_and_input"] = remote_read(args.serial, sysfs)

    if args.pull_vendor_boot:
        vb_path = args.out / "vendor_boot.readonly.img"
        evidence["vendor_boot"] = vendor_boot_copy(args.serial, args.vendor_boot_block,
                                                    vb_path, args.vendor_boot_max_mib * 1024 * 1024)

    report = args.out / "goodix-recovery-readonly.json"
    report.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(evidence, indent=2))
    print(f"Report: {report}")
    if not remote_files:
        print("No named blobs/modules found in already-present vendor trees. No mount was attempted; use an offline extracted vendor image or explicitly supplied vendor_boot block.", file=sys.stderr)


if __name__ == "__main__":
    main()
