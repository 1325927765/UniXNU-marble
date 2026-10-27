#!/usr/bin/env python3
"""Execute the exact packed ARM64 shim in QEMU and inspect its copied bytes."""
import argparse
import hashlib
import json
from pathlib import Path
import socket
import struct
import subprocess
import sys
import time
import zlib

ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'sources/UniXNU/scripts/qemu-entry'))
from gdb_packets import Packets


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--entry-probe',action='store_true')
    parser.add_argument('--post-mmu',action='store_true')
    parser.add_argument("--vm-init",action="store_true")
    parser.add_argument("--timer",action="store_true")
    parser.add_argument("--machine-startup",action="store_true")
    parser.add_argument("--checkpoint",choices=['serial-init','console-init','dt-panic-console','dt-panic-timer','dt-panic-machine','dt-panic-vm-bootstrap','dt-panic-idle','dt-panic-cpu','dt-panic-opcode','vtimer-timer','vtimer-wait'])
    args=parser.parse_args()
    if sum([args.entry_probe,args.post_mmu,args.vm_init,args.timer,args.machine_startup,bool(args.checkpoint)])>1:parser.error('Choose one diagnostic profile')
    out=ROOT/'out/UNTESTED-marble-xnu-machine-startup' if args.machine_startup else (ROOT/('out/UNTESTED-marble-xnu-timer' if args.timer else ('out/UNTESTED-marble-xnu-vm-init' if args.vm_init else ('out/UNTESTED-marble-xnu-post-mmu' if args.post_mmu else ('out/UNTESTED-marble-xnu-entry-probe' if args.entry_probe else 'out/UNTESTED-marble-early-boot')))))
    if args.checkpoint:out=ROOT/('out/UNTESTED-marble-xnu-'+args.checkpoint)
    report=json.loads((out/'boot.json').read_text())
    image=(out/report.get('image_file','marble-real-xnu-early-test.img')).read_bytes()
    size,=struct.unpack_from('<I',image,8)
    decoder=zlib.decompressobj(16+zlib.MAX_WBITS)
    body=decoder.decompress(image[4096:4096+size])+decoder.flush()
    assert hashlib.sha256(image).hexdigest()==report['image_sha256']
    directory=ROOT/'research/qemu-machine-startup-shim-20261023' if args.machine_startup else (ROOT/('research/qemu-timer-shim-20261023' if args.timer else ('research/qemu-vm-init-shim-20261023' if args.vm_init else ('research/qemu-post-mmu-shim-20261023' if args.post_mmu else ('research/qemu-entry-probe-shim-20261023' if args.entry_probe else 'research/qemu-early-shim-20261023')))))
    if args.checkpoint:directory=ROOT/('research/qemu-'+args.checkpoint+'-shim-20261023')
    directory.mkdir(parents=True,exist_ok=True)
    (directory/'image.bin').write_bytes(body)
    results={}
    for label,base,publish in [('reserved-kernel-buffer',0xA8000000,True),('outside-reserved-buffer',0x50000000,False)]:
        with socket.socket() as reservation:
            reservation.bind(('127.0.0.1',0));port=reservation.getsockname()[1]
        command=['qemu-system-aarch64','-M','virt,virtualization=off,secure=off,gic-version=3',
                 '-cpu','cortex-a710','-m','2048','-smp','1','-display','none','-monitor','none','-nic','none',
                 '-serial','none','-no-reboot','-gdb',f'tcp:127.0.0.1:{port}','-S',
                 '-device',f'loader,file={directory}/image.bin,addr={hex(base)},cpu-num=0,force-raw=on']
        with (directory/(label+'.log')).open('w') as log:
            process=subprocess.Popen(command,stdout=log,stderr=log)
            try:
                deadline=time.monotonic()+5
                while True:
                    try:connection=socket.create_connection(('127.0.0.1',port),timeout=5);break
                    except ConnectionRefusedError:
                        if time.monotonic()>deadline:raise
                        time.sleep(0.02)
                with connection:
                    connection.setsockopt(socket.IPPROTO_TCP,socket.TCP_NODELAY,1)
                    packet=Packets(connection).request
                    packet('qSupported')
                    assert packet('Z1,a7100000,4')=='OK'
                    initial=bytes.fromhex(packet('g'))
                    print('Shim initial PC:',hex(struct.unpack_from('<Q',initial,256)[0]),flush=True)
                    try:
                        stopped=packet('c')
                    except TimeoutError:
                        connection.sendall(b'\x03')
                        packet(None)
                        state=bytes.fromhex(packet('g'))
                        failure={'pc':hex(struct.unpack_from('<Q',state,256)[0]),
                                 'registers':[hex(v) for v in struct.unpack_from('<33Q',state)]}
                        (directory/(label+'-failure.json')).write_text(json.dumps(failure,indent=2)+'\n')
                        raise RuntimeError(f'Shim did not reach firmware entry: {failure}')
                    regs=bytes.fromhex(packet('g'))
                    pc=struct.unpack_from('<Q',regs,256)[0]
                    assert pc==0xA7100000,(stopped,hex(pc))
                    actual=bytearray()
                    for offset in range(0,0x300000,0x4000):
                        chunk=packet(f'm{0xA7100000+offset:x},4000')
                        assert len(chunk)==0x8000 and not chunk.startswith('E')
                        actual.extend(bytes.fromhex(chunk))
                    expected=bytearray(body[report['shim_bytes']:report['shim_bytes']+0x300000])
                    address=base+report['payload_image_offset'] if publish else 0
                    struct.pack_into('<Q',expected,report['descriptor_fd_offset']+16,address)
                    assert actual==expected,'Copied firmware differs from exact source plus runtime descriptor address'
                    if publish:
                        sector=bytes.fromhex(packet(f'm{address:x},200'))
                        assert sector==body[report['payload_image_offset']:report['payload_image_offset']+512]
                    results[label]={'pass':True,'entry_pc':hex(pc),'published_address':hex(address),
                                    'copied_fd_sha256':hashlib.sha256(actual).hexdigest()}
            finally:
                if process.poll() is None:process.terminate()
                process.wait(timeout=10)
    result={'image_sha256':report['image_sha256'],'exact_shim_execution':'PASS','cases':results,
            'scope':'QEMU executes exact final shim to copied firmware entry; board firmware itself is not executed'}
    (directory/'result.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))


if __name__=='__main__':main()
