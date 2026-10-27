#!/usr/bin/env python3
"""Pack and independently unpack a marble temporary boot image with real XNU."""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import uuid
import zlib

ROOT=Path(__file__).resolve().parent
OUT=ROOT/'out/UNTESTED-marble-early-boot'


def compile_shim(directory,fd_size,descriptor,payload_size):
    offset=fd_size+4096
    size=offset+payload_size
    obj=directory/'early-shim.o'; binary=directory/'early-shim.bin'
    subprocess.run(['clang','--target=aarch64-none-elf','-c','-DFD_BASE=0xA7100000',f'-DFD_SIZE={fd_size}',
                    f'-DIMAGE_SIZE={size}',f'-DPAYLOAD_OFFSET={offset}',f'-DPAYLOAD_SIZE={payload_size}',
                    f'-DDESCRIPTOR_OFFSET={descriptor}',ROOT/'device/early/BootShim.S','-o',obj],check=True)
    subprocess.run(['llvm-objcopy','-O','binary',obj,binary],check=True)
    symbols=subprocess.check_output(['llvm-nm','-n',obj],text=True)
    length=int(next(line.split()[0] for line in symbols.splitlines() if line.endswith(' _Payload')),16)
    data=binary.read_bytes()
    assert length==len(data) and len(data)<4096
    assert struct.unpack_from('<QQ',data,8)==(0xA7100000,size) and data[56:60]==b'ARM\x64'
    return data,offset


def main():
    global OUT
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run',type=Path)
    parser.add_argument('--entry-probe',action='store_true')
    parser.add_argument('--post-mmu',action='store_true')
    parser.add_argument("--vm-init",action="store_true")
    parser.add_argument("--timer",action="store_true")
    parser.add_argument("--machine-startup",action="store_true")
    parser.add_argument("--checkpoint",choices=['serial-init','console-init','dt-panic-console','dt-panic-timer','dt-panic-machine','dt-panic-vm-bootstrap','dt-panic-idle','dt-panic-cpu','dt-panic-opcode','vtimer-timer','vtimer-wait'])
    args=parser.parse_args(); run=args.run.resolve()
    if sum([args.entry_probe,args.post_mmu,args.vm_init,args.timer,args.machine_startup,bool(args.checkpoint)])>1:parser.error('Choose one diagnostic profile')
    if args.entry_probe or args.post_mmu or args.vm_init or args.timer or args.machine_startup:OUT=ROOT/'out/UNTESTED-marble-xnu-machine-startup' if args.machine_startup else (ROOT/('out/UNTESTED-marble-xnu-timer' if args.timer else ('out/UNTESTED-marble-xnu-vm-init' if args.vm_init else ('out/UNTESTED-marble-xnu-post-mmu' if args.post_mmu else 'out/UNTESTED-marble-xnu-entry-probe'))))
    if args.checkpoint:OUT=ROOT/('out/UNTESTED-marble-xnu-'+args.checkpoint)
    subprocess.run([sys.executable,ROOT/'validate-baseline.py',run],check=True)
    fd=(run/'SILICIUM_UEFI.fd').read_bytes()
    fat=(OUT/'payload-fat.img').read_bytes()
    meta=json.loads((OUT/'payload.json').read_text())
    assert len(fd)==0x300000 and len(fat)==0x4000000
    assert hashlib.sha256(fat).hexdigest()==meta['payload_sha256']
    magic=b'MARBLEXNUPAYLD1\0'
    assert fd.count(magic)==1,'Runtime descriptor must be uncompressed and unique'
    descriptor=fd.index(magic)
    assert descriptor%4==0 and fd[descriptor:descriptor+64]==bytes.fromhex(meta['descriptor_hex'])
    file_start=descriptor-4-24
    assert fd[file_start:file_start+16]==uuid.UUID('5C9D5E94-47F5-4C61-AD6E-987C2420D91B').bytes_le
    assert fd[file_start+18]==2 and not fd[file_start+19]&0x40,'Raw FFS must permit runtime data publication without a data checksum'
    shim,payload_offset=compile_shim(OUT,len(fd),descriptor,len(fat))
    body=shim+fd+bytes(payload_offset-len(shim)-len(fd))+fat
    dtb=(run/'marble.dtb').read_bytes()
    compressed=gzip.compress(body,mtime=0)+dtb
    (OUT/'Image.gz-dtb').write_bytes(compressed)
    image=OUT/'marble-xnu-machine-startup-test.img' if args.machine_startup else (OUT/('marble-xnu-timer-test.img' if args.timer else ('marble-xnu-vm-init-test.img' if args.vm_init else ('marble-xnu-post-mmu-reset-test.img' if args.post_mmu else ('marble-xnu-entry-diagnostic.img' if args.entry_probe else 'marble-real-xnu-early-test.img')))))
    if args.checkpoint:image=OUT/('marble-xnu-'+args.checkpoint+'-test.img')
    subprocess.run([sys.executable,ROOT/'sources/Mu-Silicium-marble/Resources/Scripts/mkbootimg.py',
                    '--kernel',OUT/'Image.gz-dtb','--ramdisk',run/'ramdisk','--header_version','4','-o',image],check=True)
    packed=image.read_bytes()
    ksize,rsize,_,header=struct.unpack_from('<4I',packed,8)
    assert packed[:8]==b'ANDROID!' and header==1584 and struct.unpack_from('<I',packed,40)[0]==4
    decoder=zlib.decompressobj(16+zlib.MAX_WBITS)
    recovered=decoder.decompress(packed[4096:4096+ksize])+decoder.flush()
    assert decoder.eof and decoder.unused_data==dtb and recovered==body
    assert recovered[len(shim):len(shim)+len(fd)]==fd and recovered[payload_offset:]==fat
    roff=4096+((ksize+4095)//4096)*4096
    ramdisk=(run/'ramdisk').read_bytes()
    assert rsize==len(ramdisk) and packed[roff:roff+rsize]==ramdisk
    soff=roff+((rsize+4095)//4096)*4096
    assert struct.unpack_from('<I',packed,1580)[0]==4096 and packed[soff:]==bytes(4096)
    # Extract actual FAT members and compare, independently of host staging.
    verify=OUT/'verify-fat';verify.mkdir(exist_ok=True)
    for name in ('kernel.macho','kernel.macho.adt'):
        target=verify/name;target.unlink(missing_ok=True)
        subprocess.run(['mcopy','-i',OUT/'payload-fat.img',f'::/EFI/UniXNU/Payloads/{name}',target],check=True)
        assert target.read_bytes()==(OUT/'payload-stage/EFI/UniXNU/Payloads'/name).read_bytes()
    report={**meta,'image_file':image.name,'image_sha256':hashlib.sha256(packed).hexdigest(),'image_bytes':len(packed),
            'fd_sha256':hashlib.sha256(fd).hexdigest(),'fd_size':len(fd),'shim_bytes':len(shim),
            'descriptor_fd_offset':descriptor,'payload_image_offset':payload_offset,'decompressed_image_bytes':len(body),
            'original_kernel_reserved_buffer':{'base':'0xa8000000','end':'0xb8000000'},
            'container_roundtrip':'PASS','fat_members_roundtrip':'PASS','header_version':4,
            'gki_signature':'zero placeholder, unlocked temporary boot only','hardware_boot_tested':False,
            'contains_real_xnu':True,'contains_apple_userspace':False,'firmware_build_run':str(run)}
    (OUT/'boot.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))


if __name__=='__main__':main()
