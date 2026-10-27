"""Observe a real HFSX md0 root mount in QEMU; no phone or iOS boot claim."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys

ROOT=Path(__file__).resolve().parent
ap=argparse.ArgumentParser(description=__doc__)
ap.add_argument('--kernel',type=Path,required=True)
ap.add_argument('--symbols',type=Path,required=True)
ap.add_argument('--image',type=Path,required=True)
ap.add_argument('--output',type=Path,required=True)
ap.add_argument('--invalid-header',action='store_true')
ap.add_argument('--hfs-only',action='store_true')
ap.add_argument('--witness',action='store_true',help='Observe the actual deliberate post-mount success panic')
args=ap.parse_args()
out=args.output.resolve(); out.mkdir(parents=True,exist_ok=True)
kernel=args.kernel.resolve()
esp=out/'esp'
shutil.copytree(ROOT/'research/qemu-vtimer-timer-20261023/esp',esp,dirs_exist_ok=True)
payload=esp/'EFI/UniXNU/Payloads'
data=bytearray(args.image.read_bytes())
assert len(data) in (16*1024*1024,64*1024*1024) and data[1024:1026]==b'HX'
if args.invalid_header:
    # Corrupt both volume headers; HFS must not mount the control image.
    data[1024:1026]=b'XX'
    data[-1024:-1022]=b'XX'
(payload/'hfs-fixture.img').write_bytes(data)
shutil.copyfile(kernel,payload/'kernel.macho')
config=esp/'EFI/UniXNU/unixnu.toml'
config.write_text(config.read_text().replace('args = "-v',
    'initrd = "Payloads/hfs-fixture.img"\nargs = "rd=md0 marble_hfs_fixture=1 -v'))
if args.witness:
    assert not args.invalid_header and not args.hfs_only
    config.write_text(config.read_text().replace('marble_hfs_fixture=1','marble_hfs_fixture=1 marble_hfs_stop=1'))
subprocess.run([sys.executable,ROOT/'sources/UniXNU/scripts/qemu-entry/make-dt.py',
    '--output',payload/'kernel.macho.adt','--dram-size',str(1024**3),
    '--owned-memory-size','0x20000000','--armvirt','--armcpu','--nvram-proxy','--ramdisk'],check=True)
symbols={m[1]:int(m[0],16) for m in re.findall(
    r'^([0-9a-fA-F]+)\s+\S\s+(\S+)$',args.symbols.read_text(),re.M)}
target='_hfs_mount' if args.hfs_only else '_vfs_mountroot'
if args.witness: target='_panic'
wanted={'_rootdev':4,'_rootdevice':16,'_source_corecrypto14_status':4,'_prng_ready':4}
requests={n:f'{symbols[n]:x}:{size:x}' for n,size in wanted.items()}
command=[sys.executable,ROOT/'sources/UniXNU/scripts/qemu-entry/gdb-stop.py',
    hex(symbols[target]),'--fixture',out,'--esp',esp,'--kernel',kernel,
    '--firmware','/usr/share/AAVMF/AAVMF_CODE.fd','--system-registers',
    '--gic-version','3','--timeout','90',
    '--trace-address',hex(symbols['_bsd_init']),
    '--trace-address',hex(symbols['_marble_hfs_register'])]
if not args.witness: command+=['--also-stop',hex(symbols['_panic']),'--finish-function']
for request in requests.values(): command+=['--read-memory',request]
with (out/'observer.log').open('w') as log:
    subprocess.run([str(v) for v in command],stdout=log,stderr=subprocess.STDOUT,check=True)
observed=json.loads((out/'gdb-stop.json').read_text())
values={n:int.from_bytes(bytes.fromhex(observed['memory'][r]),'little')
        for n,r in requests.items() if n!='_rootdevice'}
rootdevice=bytes.fromhex(observed['memory'][requests['_rootdevice']]).split(b'\0')[0].decode()
result=int(observed['x0'],16)
returned=observed.get('function_return_stack_matched',False)
expected=(22 if args.hfs_only else 19) if args.invalid_header else 0
passed=bool(returned and result==expected and rootdevice=='md0' and
            values['_source_corecrypto14_status']==0 and values['_prng_ready']==1)
if args.witness:
    passed=bool(int(observed['pc'],16)==symbols['_panic'] and
        observed.get('argument_memory',{}).get('x0','').startswith('MARBLE HFS ROOT MOUNT OK') and
        rootdevice=='md0' and values['_source_corecrypto14_status']==0 and values['_prng_ready']==1)
report={'scope':'QEMU md0/HFSX fixture, not phone UFS or iOS userspace',
        'kernel_sha256':hashlib.sha256(kernel.read_bytes()).hexdigest(),
        'image_sha256':hashlib.sha256(data).hexdigest(),'observed_function':target,
        'invalid_header':args.invalid_header,'expected_return':None if args.witness else expected,
        'actual_return':None if args.witness else result,'success_witness_observed':args.witness and passed,
        'function_return_observed':returned,'root_device':rootdevice,'globals':values,
        'root_filesystem_mounted':bool(passed and not args.invalid_header and not args.hfs_only),
        'ios_userspace_booted':False,'pass':passed}
(out/'result.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report,indent=2))
if not passed: raise SystemExit(1)
