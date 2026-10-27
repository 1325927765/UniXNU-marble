#!/usr/bin/env python3
"""Temporary 8796 phone image: read-only UFS mount of the existing HFS root.

Does not call adb or fastboot. The kernel must already contain the mode-9
root selector and the MARBLE HFS ROOT MOUNT OK stop. QEMU display tracing
stays off the command line. DarwinBoot in the firmware image must place
boot_args and the ADT on 16K boundaries.
"""
import gzip
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import uuid
import zlib

ROOT = Path(__file__).resolve().parent
PAGE = 0x4000
CMDLINE = (
    "rd=marbleufs0 marble_hfs_fixture=1 marble_hfs_stop=1 marble_ufs_probe=9 "
    "-v serial=3 debug=0x14e cpus=1 kt_fixed_zones=120"
)


def run(*cmd, **kwargs):
    return subprocess.run([str(x) for x in cmd], check=True, **kwargs)


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def sha(data):
    return hashlib.sha256(data).hexdigest()


def segments(kernel):
    magic, _, _, _, ncmds, _, _, _ = struct.unpack_from("<8I", kernel, 0)
    if magic != 0xFEEDFACF:
        raise SystemExit("kernel is not a 64-bit Mach-O")
    found = []
    off = 32
    for _ in range(ncmds):
        cmd, size = struct.unpack_from("<II", kernel, off)
        if cmd == 0x19:
            vmaddr, vmsize = struct.unpack_from("<2Q", kernel, off + 24)
            if vmsize:
                found.append((vmaddr, vmsize))
        off += size
    if not found:
        raise SystemExit("kernel has no segments")
    base = min(addr for addr, _ in found)
    end = max(addr + size for addr, size in found)
    if base & (PAGE - 1):
        raise SystemExit(f"kernel VA base {base:#x} is not 16K aligned")
    for addr, size in found:
        if addr & (PAGE - 1) or size & (PAGE - 1):
            raise SystemExit(f"segment {addr:#x}+{size:#x} is not 16K aligned")
    if end - base > 0x10000000 - 0x200000:
        raise SystemExit("kernel does not fit the 256 MiB DarwinBoot window")
    return base, end


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--kernel', type=Path, default=ROOT / 'research/marble8796-20261024/boot-visible.macho')
    parser.add_argument('--out', type=Path, default=ROOT / 'out/UNTESTED-marble8796-hfs-mount')
    parser.add_argument('--require-32m', action='store_true', help='Require the corrected 32MiB-congruent loader')
    parser.add_argument('--enable-kprintf', action='store_true', help='Enable DEVELOPMENT kernel kprintf checkpoints')
    parser.add_argument('--continue-userspace', action='store_true', help='Continue past the HFS mount stop using the existing external root')
    parser.add_argument('--allow-unsealed-hfs-test', action='store_true', help='Explicit DEVELOPMENT policy for the converted readonly HFS root')
    parser.add_argument('--allow-shared-cache-test', action='store_true', help='Set only CSR_ALLOW_UNRESTRICTED_FS for the converted HFS runtime test')
    parser.add_argument('--owner-boot-identity', action='store_true', help='Publish a non-Apple digest of these custom boot inputs for the userspace preboot lookup')
    parser.add_argument('--ufs-same-data-write-probe', action='store_true', help='Stop after one partition-bounded same-data write/readback diagnostic; no userspace')
    parser.add_argument('--allow-ufs-root-write', action='store_true', help='Opt into actual userdata partition writes during the iOS runtime trial')
    parser.add_argument('--no-effaceable-storage', action='store_true', help='Use the development keybag plist on this device without Apple effaceable storage')
    parser.add_argument('--development-launchd-cache', action='store_true', help='Use launchd own unsecure-cache development path without an AppleMobileFileIntegrity IOService')
    parser.add_argument('--boot-framebuffer-display', action='store_true', help='Enable the phone display nub backed by the actual GOP framebuffer')
    parser.add_argument('--quiet-gui-console', action='store_true', help='Stop drawing kernel console text after first GUI swap; panic output retained')
    parser.add_argument('--touch-state-probe', action='store_true', help='Opt into a read-only GCC/GENI clock/register snapshot; no touch-controller transaction')
    parser.add_argument('--touch-clock-probe', action='store_true', help='Temporarily enable only the S4 clock vote, read controller info, then restore; no touch-controller transaction')
    parser.add_argument('--touch-prereq-probe', action='store_true', help='Read-only SMMU, GPI context/status and TLMM prerequisite snapshot; no DMA or register writes')
    parser.add_argument('--firmware', type=Path, help='Pinned marble SILICIUM_UEFI.fd input')
    parser.add_argument('--firmware-run', type=Path, help='Prepared firmware build run containing DarwinBoot inputs')
    parser.add_argument('--fdt', type=Path, help='Read-only marble DTB input captured from the target device')
    parser.add_argument('--mkbootimg', type=Path, help='Pinned Mu-Silicium mkbootimg.py source')
    parser.add_argument('--trace-graphics-output', action='store_true', help='Opt into bounded backboardd and SpringBoard null-output diagnostics')
    parser.add_argument('--trace-graphics-services', action='store_true', help='Record bounded graphics process service matching, opens and waits')
    parser.add_argument('--synthetic-platform-uuid', action='store_true', help='Enable stable lab IOPlatformUUID inputs for CurrentHost preferences')
    parser.add_argument('--trace-hfs-errors', action='store_true', help='Enable bounded HFS clonefile and UFS strategy failure diagnostics')
    parser.add_argument('--sample-ui-stacks', action='store_true', help='Capture three bounded UI process stack samples at 90/150/210 seconds')
    parser.add_argument('--audit-ui-assets', action='store_true', help='Read-only one-shot UI bundle size and CRC audit before launchd')
    parser.add_argument('--reset-mg-cache', action='store_true', help='Preserve MobileGestalt cache via exclusive rename before launchd; requires writable userspace')
    parser.add_argument('--hid-home-test-seconds', type=int, default=0, help='Opt-in three synthetic Home presses, interval 30..300 seconds; does not implement hardware touch')
    parser.add_argument('--iphone-x-ui', action='store_true', help='Select iPhone X userspace identity and gesture layout, retaining Marble hardware')
    args = parser.parse_args()
    if args.iphone_x_ui and not args.continue_userspace:
        parser.error('--iphone-x-ui requires --continue-userspace')
    cmdline = CMDLINE + (' -enable_kprintf_spam' if args.enable_kprintf else '')
    if args.continue_userspace:
        cmdline = cmdline.replace('marble_hfs_stop=1 ', '')
        cmdline += ' unentitled_ios_sim_launch=1 marble_crash_log=1 keepsyms=1'
    if args.allow_unsealed_hfs_test:
        if not args.continue_userspace:
            parser.error('--allow-unsealed-hfs-test requires --continue-userspace')
        cmdline += ' marble_allow_unsealed_hfs_root=1'
    if args.allow_shared_cache_test and not args.continue_userspace:
        parser.error('--allow-shared-cache-test requires --continue-userspace')
    if args.ufs_same_data_write_probe:
        if args.continue_userspace or args.allow_unsealed_hfs_test or args.allow_shared_cache_test or args.owner_boot_identity or args.allow_ufs_root_write:
            parser.error('same-data write probe must stop before filesystem mount/userspace policies')
        cmdline = cmdline.replace('marble_hfs_stop=1 ', '')
        cmdline += ' marble_ufs_write=1 marble_ufs_write_probe=1'
    if args.allow_ufs_root_write:
        if not (args.continue_userspace and args.allow_unsealed_hfs_test and args.allow_shared_cache_test and args.owner_boot_identity):
            parser.error('--allow-ufs-root-write requires the complete existing userspace trial policies')
        cmdline += ' marble_ufs_write=1'
    if args.no_effaceable_storage and not args.continue_userspace:
        parser.error('--no-effaceable-storage requires --continue-userspace')
    if args.development_launchd_cache:
        if not args.continue_userspace:
            parser.error('--development-launchd-cache requires --continue-userspace')
        cmdline += ' launchd_unsecure_cache=1'
    if args.synthetic_platform_uuid and not args.continue_userspace:
        parser.error('--synthetic-platform-uuid requires --continue-userspace')
    if args.trace_hfs_errors:
        if not args.continue_userspace:
            parser.error('--trace-hfs-errors requires --continue-userspace')
        cmdline += ' marble_hfs_error_trace=1'
    if args.sample_ui_stacks:
        if not args.continue_userspace:
            parser.error('--sample-ui-stacks requires --continue-userspace')
        cmdline += ' marble_ui_sample=1'
    if args.audit_ui_assets:
        if not args.continue_userspace:
            parser.error('--audit-ui-assets requires --continue-userspace')
        cmdline += ' marble_asset_audit=1'
    if args.reset_mg_cache:
        if not (args.continue_userspace and args.allow_ufs_root_write and args.iphone_x_ui):
            parser.error('--reset-mg-cache requires writable userspace and iPhone X identity')
        cmdline += ' marble_mg_cache_reset=1'
    if args.hid_home_test_seconds:
        if not args.continue_userspace or not 30 <= args.hid_home_test_seconds <= 300:
            parser.error('--hid-home-test-seconds requires userspace and a 30..300 second interval')
        cmdline += f' marblehidtest={args.hid_home_test_seconds}'
    if args.boot_framebuffer_display and not args.continue_userspace:
        parser.error('--boot-framebuffer-display requires --continue-userspace')
    if args.quiet_gui_console:
        if not (args.continue_userspace and args.boot_framebuffer_display):
            parser.error('--quiet-gui-console requires the display userspace trial')
        cmdline += ' marblefb_noconsole=1'
    if sum((args.touch_state_probe, args.touch_clock_probe, args.touch_prereq_probe)) > 1:
        parser.error('select only one touch probe mode')
    if args.touch_state_probe or args.touch_clock_probe or args.touch_prereq_probe:
        if not args.continue_userspace:
            parser.error('touch probes require --continue-userspace')
        cmdline += ' marbletouchprobe=' + ('3' if args.touch_prereq_probe else ('2' if args.touch_clock_probe else '1'))
    if args.trace_graphics_output:
        if not (args.continue_userspace and args.boot_framebuffer_display):
            parser.error('--trace-graphics-output requires the display userspace trial')
        cmdline += ' marble_null_trace=1'
    if args.trace_graphics_services:
        if not (args.continue_userspace and args.boot_framebuffer_display):
            parser.error('--trace-graphics-services requires the display userspace trial')
        cmdline += ' marble_graphics_services=1'
    kernel_path = args.kernel.resolve()
    fdt = args.fdt or ROOT / "research/hardware-readonly-20261023/marble-live.dtb"
    local_firmware_root = Path.home() / "rom-lab/unixnu-marble"
    fd_path = args.firmware or local_firmware_root / "sources/Mu-Silicium-marble/Build/marblePkg/RELEASE_CLANGPDB/FV/SILICIUM_UEFI.fd"
    firmware_run = args.firmware_run or local_firmware_root / "build-runs/20261023T041341Z-early-xnu"
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)

    original = kernel_path.read_bytes()
    if (args.touch_state_probe or args.touch_clock_probe or args.touch_prereq_probe) and any(marker not in original for marker in
            (b'MarbleTouchProbe', b'marbletouchprobe', b'MARBLE TOUCH PROBE:')):
        parser.error('touch probes require the guarded snapshot service in the kernel')
    if args.touch_clock_probe and any(marker not in original for marker in
            (b'MARBLE TOUCH CLOCK:', b'marble_spi_clock_probe')):
        parser.error('--touch-clock-probe requires the bounded clock-vote implementation in the kernel')
    if args.touch_prereq_probe and any(marker not in original for marker in
            (b'MARBLE TOUCH PREREQ:', b'_marble_touch_prereq_snapshot\0', b'_marble_smmu_decode_stream\0')):
        parser.error('--touch-prereq-probe requires the read-only prerequisite module in the kernel')
    if args.quiet_gui_console and any(symbol not in original for symbol in
            (b'_marble_console_pause_video\0', b'_marble_console_video_paused\0')):
        raise SystemExit('kernel lacks the panic-aware GUI console pause implementation')
    if args.hid_home_test_seconds and (b'marblehidtest' not in original or b'MarbleHIDButtons' not in original):
        raise SystemExit('kernel lacks Marble HID Home test support')
    if args.sample_ui_stacks and b'MARBLE SMP BEGIN' not in original:
        raise SystemExit('kernel lacks bounded UI stack sampler')
    if args.trace_hfs_errors and (b'MARBLE HFSERR' not in original or b'MARBLE UFSERR' not in original):
        raise SystemExit('kernel lacks bounded HFS/UFS error tracing')
    if args.trace_graphics_output and b'marble_null_trace' not in original:
        raise SystemExit('kernel has no bounded graphics null-output tracer')
    if args.trace_graphics_services and b'MARBLE GFX %u %s[%d]' not in original:
        raise SystemExit('kernel has no bounded graphics service tracer')
    if args.boot_framebuffer_display and (b'marble,display' not in original or b'MARBLE FB: no boot framebuffer' not in original):
        raise SystemExit('kernel does not contain the boot-framebuffer display implementation')
    if args.ufs_same_data_write_probe and b'MARBLE UFS SAME DATA WRITE OK' not in original:
        raise SystemExit('kernel does not implement the same-data write diagnostic')
    if args.allow_ufs_root_write and b'_marble_ufs_root_write_enabled\0' not in original:
        raise SystemExit('kernel has no UFS root write capability export')
    if args.allow_unsealed_hfs_test and b'marble_allow_unsealed_hfs_root' not in original:
        raise SystemExit('kernel does not implement the DEVELOPMENT HFS root policy')
    for needle in (b"MARBLE HFS ROOT MOUNT OK", b"MARBLE FBCON GOP", b"marbleufs0", b"rd=marbleufs0"):
        if needle == b"rd=marbleufs0":
            continue
        if needle not in original:
            raise SystemExit(f"kernel is missing {needle!r}")
    if b"marble_disp_trace=1" in CMDLINE.encode():
        raise SystemExit("phone command line must not enable the QEMU display ring")

    payload_mod = module("mkpayload", ROOT / "research/reference-ios-sweet/tools/mkpayload.py")
    kernel = bytearray(original)
    macho = payload_mod.parse_macho(kernel)
    payload_mod.apply_chained_fixups(kernel, macho)
    base, end = segments(kernel)
    (out / "kernel.macho").write_bytes(kernel)

    fd = bytearray(fd_path.read_bytes())
    efi_path = fd_path.parents[1] / "AARCH64/DarwinBootPkg/Driver/DarwinBoot/OUTPUT/DarwinBoot.efi"
    efi = efi_path.read_bytes()
    if "DARWINBOOT-16K".encode("utf-16le") not in efi:
        raise SystemExit("DarwinBoot.efi does not contain the 16K handoff marker")
    if args.require_32m and '32M-CONGRUENT'.encode('utf-16le') not in efi:
        raise SystemExit('DarwinBoot.efi is missing the 32MiB allocation fix')
    if efi_path.stat().st_mtime > fd_path.stat().st_mtime:
        raise SystemExit("firmware image is older than DarwinBoot.efi")
    if len(fd) != 0x300000:
        raise SystemExit(f"unexpected firmware size {len(fd):#x}")
    magic = b"MARBLEXNUPAYLD1\0"
    if fd.count(magic) != 1:
        raise SystemExit("firmware payload descriptor is not unique")
    descriptor = fd.index(magic)
    ffs = descriptor - 28
    if fd[ffs:ffs + 16] != uuid.UUID("5C9D5E94-47F5-4C61-AD6E-987C2420D91B").bytes_le:
        raise SystemExit("payload descriptor is not in the expected firmware file")

    stage = out / "payload-stage/EFI/UniXNU"
    (stage / "Payloads").mkdir(parents=True, exist_ok=True)
    shutil.copyfile(out / "kernel.macho", stage / "Payloads/kernel.macho")
    adt = stage / "Payloads/kernel.macho.adt"
    adt_command=[sys.executable, ROOT / "make-marble-adt.py", "--fdt", fdt, "--output", adt, "--ufs-probe-node", "--xnu8796-gic"]
    if args.allow_shared_cache_test:
        adt_command.append('--allow-unrestricted-fs')
    if args.no_effaceable_storage:
        adt_command.append('--no-effaceable-storage')
    if args.boot_framebuffer_display:
        adt_command.append('--boot-framebuffer-display')
    if args.synthetic_platform_uuid:
        adt_command.append('--synthetic-platform-uuid')
    if args.iphone_x_ui:
        adt_command.append('--iphone-x-ui')
    run(*adt_command)
    adt_bytes = adt.read_bytes()
    owner_identity = None
    if args.owner_boot_identity:
        if not args.continue_userspace:
            parser.error('--owner-boot-identity requires --continue-userspace')
        codec = module('adt_codec', ROOT / 'prepare-iphone16-qemu-adt.py')
        tree, consumed = codec.read(adt_bytes)
        if consumed != len(adt_bytes):
            raise SystemExit('ADT trailing bytes')
        chosen = [n for n in tree[1] if n[0].get('name') == b'chosen\0']
        if len(chosen) != 1 or 'boot-manifest-hash' in chosen[0][0]:
            raise SystemExit('expected one unpopulated chosen identity')
        domain = b'UniXNU.Marble.OwnerBootSet.v1\0'
        owner_identity = {
            'domain': domain[:-1].decode(), 'apple_personalized': False,
            'kernel_sha384': hashlib.sha384(kernel).hexdigest(),
            'pre_identity_adt_sha384': hashlib.sha384(adt_bytes).hexdigest(),
            'firmware_sha384': hashlib.sha384(fd).hexdigest(),
            'cmdline': cmdline,
            'external_root': 'userdata HFS iOSRoot; contents not measured by this package',
        }
        canonical = json.dumps(owner_identity, sort_keys=True, separators=(',', ':')).encode()
        digest = hashlib.sha384(domain + canonical).digest()
        chosen[0][0]['boot-manifest-hash'] = digest
        chosen[0][0]['owner-boot-manifest-domain'] = domain
        adt_bytes = codec.encode(tree)
        adt.write_bytes(adt_bytes)
        owner_identity['digest_sha384'] = digest.hex()
        (out / 'owner-boot-identity.json').write_text(json.dumps(owner_identity, indent=2)+'\n')
    if (b"display-subsystem" in adt_bytes and not args.boot_framebuffer_display) or b"marble-fbcon" in adt_bytes or b"\x00\x00\x00\x9c\x00\x00\x00\x00" in adt_bytes:
        raise SystemExit("phone ADT contains a QEMU display node")
    if b"marble-ufs-probe" not in adt_bytes:
        raise SystemExit("phone ADT has no marble-ufs-probe node")
    config = f'''version = 1
[boot]
timeout = 0
default = "marble8796-hfs-mount"
[kits]
autoload = false
[[entry]]
id = "marble8796-hfs-mount"
title = "{'Marble 8796 existing iOSRoot userspace trial' if args.continue_userspace else 'Marble 8796 read-only HFS root mount'}"
type = "xnu"
path = "Payloads/kernel.macho"
args = "{cmdline}"
'''
    (stage / "unixnu.toml").write_text(config)
    fat_path = out / "payload-fat.img"
    fat_path.unlink(missing_ok=True)
    fat_sectors = 131072
    run("mformat", "-C", "-F", "-T", str(fat_sectors), "-v", "MARBLEXNU", "-N", "4D415242", "-i", fat_path, "::")
    run("mcopy", "-i", fat_path, "-s", out / "payload-stage/EFI", "::/")
    fat = fat_path.read_bytes()
    if len(fat) != fat_sectors * 512:
        raise SystemExit("payload FAT is not 64 MiB")
    updated = struct.pack("<16sQQIIQQQ", magic, 0, len(fat), zlib.crc32(fat), 1, 19200000, 0, 0)
    fd[descriptor:descriptor + 64] = updated
    (out / "SILICIUM_UEFI.fd").write_bytes(fd)
    shim, offset = module("early_pack", ROOT / "pack-early-image.py").compile_shim(
        out, len(fd), descriptor, len(fat))
    body = shim + fd + bytes(offset - len(shim) - len(fd)) + fat
    dtb = (firmware_run / "marble.dtb").read_bytes()
    compressed = gzip.compress(body, mtime=0) + dtb
    image_kernel = out / "Image.gz-dtb"
    image_kernel.write_bytes(compressed)
    image = out / "marble8796-hfs-mount.img"
    mkbootimg = args.mkbootimg or local_firmware_root / "sources/Mu-Silicium-marble/Resources/Scripts/mkbootimg.py"
    run(sys.executable, mkbootimg,
        "--kernel", image_kernel, "--ramdisk", firmware_run / "ramdisk",
        "--header_version", "4", "-o", image)
    packed = image.read_bytes()
    ksize = struct.unpack_from("<I", packed, 8)[0]
    if packed[:8] != b"ANDROID!" or struct.unpack_from("<I", packed, 40)[0] != 4:
        raise SystemExit("boot image header is not Android v4")
    decoder = zlib.decompressobj(16 + zlib.MAX_WBITS)
    recovered = decoder.decompress(packed[4096:4096 + ksize]) + decoder.flush()
    if not decoder.eof or decoder.unused_data != dtb or recovered != body:
        raise SystemExit("boot image round-trip mismatch")
    for name in ("kernel.macho", "kernel.macho.adt"):
        target = out / ("roundtrip-" + name)
        target.unlink(missing_ok=True)
        run("mcopy", "-i", fat_path, "::/EFI/UniXNU/Payloads/" + name, target)
        if target.read_bytes() != (stage / "Payloads" / name).read_bytes():
            raise SystemExit(f"{name} did not round-trip")
    result = {
        "image_sha256": sha(packed),
        "image_bytes": len(packed),
        "source_kernel_sha256": sha(original),
        "fixed_kernel_sha256": sha(kernel),
        "kernel_va_base": hex(base),
        "kernel_va_end": hex(end),
        "firmware_sha256": sha(fd),
        "payload_crc32": hex(zlib.crc32(fat)),
        "cmdline": cmdline,
        "container_and_fat_roundtrip": "PASS",
        "page_alignment": "16K",
        "requires_32m_allocation_congruence": args.require_32m,
        "expected_stop": ('MARBLE UFS SAME DATA WRITE OK' if args.ufs_same_data_write_probe else ('Continue past HFS mount toward existing /sbin/launchd; outcome unverified' if args.continue_userspace else 'MARBLE HFS ROOT MOUNT OK DEV=%llx FLAGS=%llx')),
        "same_data_partition_write_probe": args.ufs_same_data_write_probe,
        "userdata_runtime_writes_enabled": args.allow_ufs_root_write,
        "no_effaceable_storage": args.no_effaceable_storage,
        "development_launchd_unsecure_cache": args.development_launchd_cache,
        "boot_framebuffer_display_enabled": args.boot_framebuffer_display,
        "quiet_video_console_after_gui_swap": args.quiet_gui_console,
        "quiet_framebuffer_serial_after_gui_swap": args.quiet_gui_console,
        "readonly_touch_controller_state_probe": args.touch_state_probe,
        "temporary_s4_clock_probe": args.touch_clock_probe,
        "readonly_touch_dma_prereq_snapshot": args.touch_prereq_probe,
        "touch_probe_mode": 3 if args.touch_prereq_probe else (2 if args.touch_clock_probe else (1 if args.touch_state_probe else 0)),
        "physical_touch_driver_enabled": False,
        "crypto_hash_method": "sha2-384",
        "synthetic_platform_uuid_enabled": args.synthetic_platform_uuid,
        "bounded_hfs_ufs_error_trace": args.trace_hfs_errors,
        "bounded_ui_stack_samples": args.sample_ui_stacks,
        "readonly_ui_asset_audit": args.audit_ui_assets,
        "exclusive_mobilegestalt_cache_backup": args.reset_mg_cache,
        "synthetic_home_test_interval_seconds": args.hid_home_test_seconds,
        "synthetic_home_test_max_presses": 3 if args.hid_home_test_seconds else 0,
        "iphone_x_ui_identity": args.iphone_x_ui,
        "bounded_graphics_output_trace": args.trace_graphics_output,
        "bounded_graphics_service_trace": args.trace_graphics_services,
        "attempts_existing_ios_userspace": args.continue_userspace,
        "external_root_required": args.continue_userspace,
        "development_unsealed_readonly_hfs_policy": args.allow_unsealed_hfs_test,
        "development_shared_cache_fs_policy": args.allow_shared_cache_test,
        "owner_boot_identity": owner_identity,
        "temporary_boot_only": True,
        "hardware_boot_tested": False,
        "userdata_flashed": False,
        "contains_ios_userspace": False,
        "qemu_display_trace": False,
    }
    (out / "boot.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
