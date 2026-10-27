#!/usr/bin/env python3
"""Exercise the exact phone FAT reader with real owned QEMU memory buffers."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parent


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run',type=Path)
    args=parser.parse_args();run=args.run.resolve()
    out=ROOT/'research/qemu-payload-transport-20261023';out.mkdir(parents=True,exist_ok=True)
    esp=out/'esp';(esp/'EFI/BOOT').mkdir(parents=True,exist_ok=True)
    shutil.copyfile(run/'MarblePayloadFixture.efi',esp/'EFI/BOOT/BOOTAA64.EFI')
    for name in ('MarblePayloadBoot.efi','DarwinBoot.efi'):shutil.copyfile(run/name,esp/name)
    payload=out/'stage/EFI/UniXNU/Payloads';payload.mkdir(parents=True,exist_ok=True)
    kernel=ROOT/'out/UNTESTED-marble-early-xnu/marble-early-source-kernel.macho'
    shutil.copyfile(kernel,payload/'kernel.macho')
    subprocess.run([sys.executable,ROOT/'sources/UniXNU/scripts/qemu-entry/make-dt.py',
                    '--output',payload/'kernel.macho.adt','--owned-memory-size','0x20000000',
                    '--dram-size','0x80000000','--armvirt','--armcpu','--nvram-proxy'],check=True)
    (payload.parent/'unixnu.toml').write_text('''version = 1
[boot]
timeout = 1
default = "qemu-transport"
[kits]
autoload = false
[[entry]]
id = "qemu-transport"
title = "QEMU real XNU through RAM FAT"
type = "xnu"
path = "Payloads/kernel.macho"
args = "-v serial=3 debug=0x14e kt_fixed_zones=120"
''')
    fat=esp/'payload-fat.img';fat.unlink(missing_ok=True)
    env=dict(os.environ,MTOOLS_SKIP_CHECK='1',TZ='UTC')
    subprocess.run(['mformat','-C','-F','-T','131072','-v','QEMUXNU','-i',fat,'::'],check=True,env=env)
    subprocess.run(['mcopy','-i',fat,'-s',out/'stage/EFI','::/'],check=True,env=env)
    symbols={m[2]:int(m[1],16) for m in re.finditer(r'^([0-9a-fA-F]+)\s+\S\s+(\S+)$',
                (kernel.parent/'kernel-symbols.txt').read_text(),re.M)}
    positive=out/'positive';positive.mkdir(exist_ok=True)
    observations={'_armcpu_registered':4,'_armcpu_gic_ready':4,'_armcpu_timer_interrupts':8,
                  '_source_corecrypto14_status':4,'_prng_ready':4}
    requests={n:f'{symbols[n]:x}:{size:x}' for n,size in observations.items()}
    command=[sys.executable,ROOT/'sources/UniXNU/scripts/qemu-entry/gdb-stop.py',hex(symbols['_rtclock_intr']),
             '--fixture',positive,'--esp',esp,'--kernel',kernel,'--system-registers','--gic-version','3',
             '--qemu-memory-mib','2048','--firmware','/usr/share/AAVMF/AAVMF_CODE.fd',
             '--qemu-ramfb','--capture-screen','--timeout','120','--also-stop',hex(symbols['_panic'])]
    for r in requests.values():command+=['--read-memory',r]
    with (positive/'observer.log').open('w') as log:
        code=subprocess.run(command,stdout=log,stderr=subprocess.STDOUT).returncode
    if code:
        print((positive/'observer.log').read_text()[-4000:]);raise SystemExit(code)
    capture=json.loads((positive/'gdb-stop.json').read_text())
    values={n:int.from_bytes(bytes.fromhex(capture['memory'][r]),'little') for n,r in requests.items()}
    uart=(positive/'gdb-uart.log').read_text(errors='replace')
    assert 'MARBLE-PAYLOAD: real read-only FAT CRC and filesystem PASS' in uart,uart[-4000:]
    assert int(capture['pc'],16)==symbols['_rtclock_intr'],capture['pc']
    assert values['_armcpu_registered']==1 and values['_armcpu_gic_ready']==1 and values['_armcpu_timer_interrupts']>0
    assert values['_source_corecrypto14_status']==0 and values['_prng_ready']==1
    negative={}
    for flag,expected in [('bad-crc.flag','CRC Error'),('bad-address.flag','Compromised Data')]:
        marker=esp/flag;marker.write_bytes(b'owned-fixture-only')
        log=out/(flag+'.uart.log')
        command=['qemu-system-aarch64','-M','virt,virtualization=off,secure=off,gic-version=3',
                 '-cpu','cortex-a710','-m','2048','-smp','1','-display','none','-monitor','none','-nic','none',
                 '-no-reboot','-serial',f'file:{log}','-device','ramfb',
                 '-drive','if=pflash,format=raw,readonly=on,file=/usr/share/AAVMF/AAVMF_CODE.fd',
                 '-drive',f'if=none,id=esp,format=raw,readonly=on,file=fat:{esp}',
                 '-device','virtio-blk-pci,drive=esp']
        try:
            with (out/(flag+'.stderr.log')).open('w') as errors:
                process=subprocess.Popen(command,stdout=errors,stderr=errors)
                try:
                    deadline=time.monotonic()+35
                    while time.monotonic()<deadline:
                        text=log.read_text(errors='replace') if log.exists() else ''
                        if f'MARBLE-PAYLOAD: refused {expected}' in text:break
                        if process.poll() is not None:break
                        time.sleep(0.1)
                    else:raise AssertionError(f'No expected refusal for {flag}')
                    assert f'MARBLE-PAYLOAD: refused {expected}' in text,text[-3000:]
                    assert 'exiting boot services' not in text
                    negative[flag]='PASS'
                finally:
                    if process.poll() is None:process.terminate()
                    process.wait(timeout=10)
        finally:marker.unlink(missing_ok=True)
    report={'scope':'QEMU-only test fixture prepares real allocated RAM; exact phone reader binary',
            'reader_sha256':hashlib.sha256((run/'MarblePayloadBoot.efi').read_bytes()).hexdigest(),
            'kernel_sha256':hashlib.sha256(kernel.read_bytes()).hexdigest(),
            'real_fat_to_xnu_timer_interrupt':'PASS','globals':values,'negative_controls':negative,
            'fixture_embedded_in_phone_fd':False,'marble_hardware_tested':False}
    (out/'result.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))


if __name__=='__main__':main()
