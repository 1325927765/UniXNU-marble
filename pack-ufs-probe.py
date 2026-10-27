#!/usr/bin/env python3
"""Build a temporary UFS-register diagnostic image using audited marble firmware.

Run inside the WSL lab. All output is local; this script never calls adb/fastboot.
"""
import argparse
import gzip
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import uuid
import zlib

ROOT = Path(__file__).resolve().parent


def run(*cmd, **kwargs):
    return subprocess.run([str(x) for x in cmd], check=True, **kwargs)


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def sha(data):
    return hashlib.sha256(data).hexdigest()


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--kernel', type=Path, required=True)
    ap.add_argument('--report', type=Path, required=True)
    ap.add_argument('--fdt', type=Path, required=True)
    ap.add_argument('--probe-mode', type=int, choices=(2, 3, 4, 5, 6, 7, 8, 9), default=2)
    ap.add_argument('--hfs-image',type=Path,help='Mode 8: owned 16 MiB HFSX RAM root fixture, not iOS')
    ap.add_argument('--output', type=Path)
    args = ap.parse_args()
    out = args.output.resolve() if args.output else ROOT / 'out/UNTESTED-marble-ufs-readonly'
    out.mkdir(parents=True, exist_ok=True)
    report = json.loads(args.report.read_text())
    original = args.kernel.read_bytes()
    assert report['kernel_built'] and report['marble_ufs_readonly_probe_requested']
    assert report['marble_virtual_timer_only_patch_requested']
    assert sha(original) == report['kernel_sha256']
    expected_format = {2:b'MARBLE UFS READ OK HCE:HCS=', 3:b'MARBLE UFS QUEUE READ DBR:RSR=',
                       4:b'MARBLE UFS GPT OK USERDATA',5:b'MARBLE UFS SENSE RAW=',
                       6:b'MARBLE UFS ACTIVE: one Device W-LUN initialization request',
                       7:b'MARBLE UFS BSD READ OK DEV=',8:b'MARBLE HFS ROOT MOUNT OK DEV=',
                       9:b'MARBLE UFS ROOT MOUNT FAIL ERR='}[args.probe_mode]
    assert expected_format in original, 'Kernel lacks the selected diagnostic mode'
    hfs_mode=args.probe_mode==8
    if args.probe_mode==9:
        assert report.get('hfs_mount_fixture_requested')
    if hfs_mode:
        assert report.get('hfs_mount_fixture_requested') and args.hfs_image
        hfs=args.hfs_image.read_bytes()
        assert len(hfs)==16*1024*1024 and hfs[1024:1026]==b'HX'
    base = json.loads((ROOT / 'out/UNTESTED-marble-xnu-vtimer-wait/boot.json').read_text())
    firmware_run = Path(base['firmware_build_run'])
    fd = bytearray((firmware_run / 'SILICIUM_UEFI.fd').read_bytes())
    assert sha(fd) == base['fd_sha256'] and len(fd) == 0x300000
    magic = b'MARBLEXNUPAYLD1\0'
    assert fd.count(magic) == 1
    descriptor = fd.index(magic)
    assert descriptor == base['descriptor_fd_offset']
    ffs = descriptor - 28
    assert fd[ffs:ffs+16] == uuid.UUID('5C9D5E94-47F5-4C61-AD6E-987C2420D91B').bytes_le
    assert fd[ffs+18] == 2 and not fd[ffs+19] & 0x40
    # Runtime payload data has no FFS data checksum; only its descriptor changes.
    kernel = out / 'kernel.macho'
    kernel.write_bytes(original)
    env = dict(os.environ, UNIXNU_UEFI=str(ROOT / 'sources/Mu-Silicium-marble'))
    run(sys.executable, ROOT/'research/entry-probe-source/scripts/patch-xnu-entry-probe.py',
        kernel, '--no-reset', env=env)
    panic = module('compact_panic_ufs', ROOT/'add-compact-panic.py').add(
        kernel, args.kernel, registers=True, after_stage=2)
    run(sys.executable, ROOT/'sources/UniXNU/scripts/seal-source-crypto-kernel.py', kernel)
    stage = out/'payload-stage/EFI/UniXNU'
    (stage/'Payloads').mkdir(parents=True, exist_ok=True)
    shutil.copyfile(kernel, stage/'Payloads/kernel.macho')
    adt = stage/'Payloads/kernel.macho.adt'
    run(sys.executable, ROOT/'make-marble-adt.py', '--fdt', args.fdt,
        '--output', adt, *(['--ramdisk'] if hfs_mode else ['--ufs-probe-node']))
    config = '''version = 1
[boot]
timeout = 3
default = "marble-ufs-probe"
[kits]
autoload = false
[[entry]]
id = "marble-ufs-probe"
title = "Marble UFS register probe (read only)"
type = "xnu"
path = "Payloads/kernel.macho"
args = "-v serial=3 debug=0x14e cpus=1 kt_fixed_zones=120 marble_ufs_probe=2"
'''
    config = config.replace('marble_ufs_probe=2', f'marble_ufs_probe={args.probe_mode}')
    if args.probe_mode==6:
        config=config.replace('Marble UFS register probe (read only)', 'Marble UFS ACTIVE + GPT read test')
    if args.probe_mode==7:
        config=config.replace('Marble UFS register probe (read only)', 'Marble UFS BSD block read test')
    if hfs_mode:
        (stage/'Payloads/hfs-fixture.img').write_bytes(hfs)
        config=config.replace('Marble UFS register probe (read only)','Marble HFSX RAM root mount test')
        config=config.replace('args = "-v','initrd = "Payloads/hfs-fixture.img"\nargs = "rd=md0 marble_hfs_fixture=1 marble_hfs_stop=1 -v')
        config=config.replace(' marble_ufs_probe=8','')
    if args.probe_mode==9:
        config=config.replace('Marble UFS register probe (read only)','Marble UFS root mount probe (read only)')
        config=config.replace('args = "-v','args = "rd=marbleufs0 marble_hfs_fixture=1 marble_hfs_stop=1 -v')
        assert 'initrd =' not in config
    (stage/'unixnu.toml').write_text(config)
    fat_path = out/'payload-fat.img'
    fat_path.unlink(missing_ok=True)
    # PayloadEntry in the audited firmware requires exactly 64 MiB.
    # A larger FAT can round-trip locally yet be refused before the menu.
    fat_sectors=131072
    run('mformat', '-C', '-F', '-T', str(fat_sectors), '-v', 'MARBLEXNU', '-N', '4D415242', '-i', fat_path, '::')
    run('mcopy', '-i', fat_path, '-s', out/'payload-stage/EFI', '::/')
    fat = fat_path.read_bytes()
    assert len(fat) == fat_sectors*512
    updated = struct.pack('<16sQQIIQQQ', magic, 0, len(fat), zlib.crc32(fat), 1, 19200000, 0, 0)
    fd[descriptor:descriptor+64] = updated
    (out/'SILICIUM_UEFI.fd').write_bytes(fd)
    shim, offset = module('early_pack_ufs', ROOT/'pack-early-image.py').compile_shim(
        out, len(fd), descriptor, len(fat))
    body = shim + fd + bytes(offset-len(shim)-len(fd)) + fat
    dtb = (firmware_run/'marble.dtb').read_bytes()
    compressed = gzip.compress(body, mtime=0) + dtb
    image_kernel = out/'Image.gz-dtb'
    image_kernel.write_bytes(compressed)
    image = out/'marble-ufs-readonly-test.img'
    run(sys.executable, ROOT/'sources/Mu-Silicium-marble/Resources/Scripts/mkbootimg.py',
        '--kernel', image_kernel, '--ramdisk', firmware_run/'ramdisk', '--header_version', '4', '-o', image)
    packed = image.read_bytes()
    ksize = struct.unpack_from('<I', packed, 8)[0]
    assert packed[:8] == b'ANDROID!' and struct.unpack_from('<I', packed, 40)[0] == 4
    decoder = zlib.decompressobj(16+zlib.MAX_WBITS)
    recovered = decoder.decompress(packed[4096:4096+ksize])+decoder.flush()
    assert decoder.eof and decoder.unused_data == dtb and recovered == body
    for name in ('kernel.macho', 'kernel.macho.adt', *(['hfs-fixture.img'] if hfs_mode else [])):
        target = out/('roundtrip-'+name)
        target.unlink(missing_ok=True)
        run('mcopy', '-i', fat_path, '::/EFI/UniXNU/Payloads/'+name, target)
        assert target.read_bytes() == (stage/'Payloads'/name).read_bytes()
    assert sha(args.kernel.read_bytes()) == report['kernel_sha256']
    result = {'image_sha256':sha(packed), 'image_bytes':len(packed),
              'source_kernel_sha256':sha(original), 'diagnostic_kernel_sha256':sha(kernel.read_bytes()),
              'firmware_base_sha256':base['fd_sha256'], 'firmware_descriptor_offset':descriptor,
              'payload_crc32':hex(zlib.crc32(fat)), 'container_and_fat_roundtrip':'PASS',
              'panic_witness':panic, 'probe_mode':args.probe_mode,
              'expected_stop':{2:'MARBLE UFS READ OK; ARG0=HCE:HCS, ARG1=CAP:VER',
                               3:'MARBLE UFS QUEUE READ; ARG0=DBR:RSR, ARG1=BAU:BA',
                               4:'MARBLE UFS GPT OK; ARG0=userdata first LBA, ARG1=count; or SCSI FAIL with stage/error',
                               5:'MARBLE UFS SENSE; ARG0=raw command/status, ARG1=LEN:FMT:KEY:ASC:ASCQ:VALID',
                               6:'MARBLE UFS GPT OK or SCSI FAIL; stage 16 = Device W-LUN ACTIVE failure',
                               7:'MARBLE UFS BSD READ OK; ARG0=major:minor, ARG1=0x1f; or SCSI FAIL stage 17-22',
                               8:'MARBLE HFS ROOT MOUNT OK; ARG0=md0 dev, ARG1=mount flags; no iOS userspace',
                               9:'UFS ROOT MOUNT FAIL expected on Android userdata; ARG0=errno, ARG1=BSD read count; HFS ROOT MOUNT OK only on real HFS volume'}[args.probe_mode],
              'controller_register_writes':args.probe_mode in (4,5,6,7,9),
              'device_active_request_enabled':args.probe_mode in (6,7,9),
              'bsd_block_device_test_enabled':args.probe_mode==7,
              'hfs_ram_root_test_enabled':hfs_mode,
              'physical_ufs_root_mount_probe':args.probe_mode==9,
              'hfs_fixture_sha256':sha(hfs) if hfs_mode else None,
              'temporary_boot_only':True, 'hardware_boot_tested':False,
              'contains_ios_userspace':False, 'physical_disk_writes':False}
    (out/'boot.json').write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
