#!/usr/bin/env python3
"""Make a read-only early XNU FAT payload and integrate its firmware reader."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import zlib

ROOT = Path(__file__).resolve().parent
UEFI = ROOT / 'sources/Mu-Silicium-marble'
BOARD = UEFI / 'Platforms/Xiaomi/marblePkg'
OUT = ROOT / 'out/UNTESTED-marble-early-boot'
MAGIC = b'MARBLEXNUPAYLD1\0'


def main():
    global OUT
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--entry-probe',action='store_true')
    parser.add_argument('--post-mmu',action='store_true')
    parser.add_argument("--vm-init",action="store_true")
    parser.add_argument("--timer",action="store_true")
    parser.add_argument("--machine-startup",action="store_true")
    parser.add_argument("--checkpoint",choices=['serial-init','console-init','dt-panic-console','dt-panic-timer','dt-panic-machine','dt-panic-vm-bootstrap','dt-panic-idle','dt-panic-cpu','dt-panic-opcode','vtimer-timer','vtimer-wait'])
    args=parser.parse_args()
    if sum([args.entry_probe,args.post_mmu,args.vm_init,args.timer,args.machine_startup,bool(args.checkpoint)])>1:parser.error('Choose one diagnostic profile')
    if args.entry_probe or args.post_mmu or args.vm_init or args.timer or args.machine_startup or args.checkpoint:
        OUT=ROOT/'out/UNTESTED-marble-xnu-machine-startup' if args.machine_startup else (ROOT/('out/UNTESTED-marble-xnu-timer' if args.timer else ('out/UNTESTED-marble-xnu-vm-init' if args.vm_init else ('out/UNTESTED-marble-xnu-post-mmu' if args.post_mmu else 'out/UNTESTED-marble-xnu-entry-probe'))))
    if args.checkpoint:OUT=ROOT/('out/UNTESTED-marble-xnu-'+args.checkpoint)
    OUT.mkdir(parents=True,exist_ok=True)
    payload = OUT / 'payload-stage/EFI/UniXNU/Payloads'
    payload.mkdir(parents=True,exist_ok=True)
    kernel = ROOT / 'out/UNTESTED-marble-early-xnu/marble-early-source-kernel.macho'
    record = json.loads((ROOT/'research/mac-build-20261023/build-report.json').read_text())
    if args.checkpoint and args.checkpoint.startswith('dt-panic-'):
        record=json.loads((ROOT/'research/mac-dt-panic-20261023/build-report.json').read_text())
        assert record['dt_panic_region_compile_verified']
    if args.checkpoint and args.checkpoint.startswith('vtimer-'):
        record=json.loads((ROOT/'research/mac-virtual-timer-only-20261023/build-report.json').read_text())
        assert record['dt_panic_region_compile_verified'] and record['virtual_timer_only_compile_verified']
    source_hash=record['kernel_sha256']
    if args.entry_probe or args.post_mmu or args.vm_init or args.timer or args.machine_startup or args.checkpoint:
        probe=json.loads((OUT/'kernel-probe.json').read_text())
        assert probe['original_kernel_sha256']==source_hash and not probe['selftests_disabled']
        kernel=OUT/'marble-entry-probe-kernel.macho'
        record={'kernel_sha256':probe['instrumented_kernel_sha256']}
    if hashlib.sha256(kernel.read_bytes()).hexdigest()!=record['kernel_sha256']:
        raise SystemExit('Actual audited source kernel hash differs')
    shutil.copyfile(kernel,payload/'kernel.macho')
    subprocess.run([sys.executable,ROOT/'make-marble-adt.py','--fdt',
                    ROOT/'research/hardware-live-20261023-connected/marble-live.dtb',
                    '--output',payload/'kernel.macho.adt'],check=True)
    config='''version = 1
[boot]
timeout = 12
default = "marble-early"
[kits]
autoload = false
[[entry]]
id = "marble-early"
title = "Marble real XNU early test"
type = "xnu"
path = "Payloads/kernel.macho"
args = "-v serial=3 debug=0x14e kt_fixed_zones=120"
'''
    if args.entry_probe or args.post_mmu or args.vm_init or args.timer or args.machine_startup or args.checkpoint:config=config.replace('Marble real XNU early test','Marble XNU machine startup' if args.machine_startup else 'Marble XNU timer diagnostic' if args.timer else ('Marble XNU VM init diagnostic' if args.vm_init else ('Marble XNU MMU reset diagnostic' if args.post_mmu else 'Marble XNU entry diagnostic')))
    if args.checkpoint:
        config=config.replace('Marble XNU entry diagnostic','Marble XNU '+args.checkpoint+' check')
    (payload.parent/'unixnu.toml').write_text(config)
    image = OUT/'payload-fat.img'
    image.unlink(missing_ok=True)
    env = dict(os.environ,MTOOLS_SKIP_CHECK='1',TZ='UTC')
    subprocess.run(['mformat','-C','-F','-T','131072','-v','MARBLEXNU','-N','4D415242','-i',image,'::'],env=env,check=True)
    subprocess.run(['mcopy','-i',image,'-s',OUT/'payload-stage/EFI','::/'],env=env,check=True)
    fat = image.read_bytes()
    descriptor = struct.pack('<16sQQIIQQQ',MAGIC,0,len(fat),zlib.crc32(fat),1,19200000,0,0)
    assert len(descriptor)==64 and len(MAGIC)==16
    subprocess.run([sys.executable,ROOT/'integrate-menu.py','--darwinboot-probe'],check=True)
    app = BOARD/'Applications/PayloadBoot'
    app.mkdir(parents=True,exist_ok=True)
    for name in ('PayloadBoot.c','PayloadBoot.inf','PayloadFixture.c','PayloadFixture.inf'):
        shutil.copyfile(ROOT/'device/early'/name,app/name)
    (app/'descriptor.bin').write_bytes(descriptor)
    dsc = BOARD/'Include/UniXNU.dsc.inc'
    text = dsc.read_text().replace('A8763D2E-EE65-4FD2-810A-63AD45E218B0','E89AC568-1D84-44C3-8F7B-C7DA84F6E2E0')
    dsc.write_text(text+'\n[Components]\n  marblePkg/Applications/PayloadBoot/PayloadBoot.inf\n  marblePkg/Applications/PayloadBoot/PayloadFixture.inf\n')
    fdf = BOARD/'Include/UniXNU.fdf.inc'
    fdf.write_text(fdf.read_text()+'\n  INF marblePkg/Applications/PayloadBoot/PayloadBoot.inf\n')
    fdf = BOARD/'marble.fdf'
    text = fdf.read_text()
    marker = '  FILE FV_IMAGE = 9E21FD93-9C72-4c15-8C4B-E77F1DB2D792 {'
    assert text.count(marker)==1
    text = text.replace(marker,'''  FILE FREEFORM = 5C9D5E94-47F5-4C61-AD6E-987C2420D91B {
    SECTION RAW = marblePkg/Applications/PayloadBoot/descriptor.bin
  }

'''+marker)
    fdf.write_text(text)
    manifest=json.loads((ROOT/'research/darwinboot-integration-inputs.json').read_text())
    for path in (dsc,BOARD/'Include/UniXNU.fdf.inc',fdf,*app.iterdir()):
        manifest[str(path.relative_to(UEFI))]=hashlib.sha256(path.read_bytes()).hexdigest()
    (ROOT/'research/early-integration-inputs.json').write_text(json.dumps(manifest,indent=2)+'\n')
    report={'kernel_sha256':record['kernel_sha256'],'original_source_kernel_sha256':source_hash,'entry_probe':bool(args.entry_probe or args.post_mmu or args.vm_init or args.timer or args.machine_startup or args.checkpoint),'checkpoint_name':args.checkpoint,'machine_startup_reset_probe':args.machine_startup,'timer_interrupt_reset_probe':args.timer or args.checkpoint in ('dt-panic-timer','vtimer-timer'),'post_mmu_reset_probe':args.post_mmu,'vm_init_reset_probe':args.vm_init,
            'payload_bytes':len(fat),'payload_sha256':hashlib.sha256(fat).hexdigest(),
            'payload_crc32':hex(zlib.crc32(fat)),'descriptor_hex':descriptor.hex(),
            'transport':'FAT appended after unchanged-size FD; original Android kernel reserved buffer; read-only Block I/O',
            'physical_disk_writes':False,'hardware_boot_tested':False}
    (OUT/'payload.json').write_text(json.dumps(report,indent=2)+'\n')
    print('Prepared real marble early payload and firmware reader; build firmware next.')


if __name__=='__main__': main()
