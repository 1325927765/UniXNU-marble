#!/usr/bin/env python3
"""Hook the actual root-wait log, draw a cyan band, then tail-call original IOLog."""
from pathlib import Path
import importlib.util,struct,tempfile
ROOT=Path(__file__).resolve().parent

def add(kernel,source,panic):
    script=ROOT/'research/entry-probe-source/scripts/patch-xnu-entry-probe.py'
    sp=importlib.util.spec_from_file_location('probe',script);m=importlib.util.module_from_spec(sp);sp.loader.exec_module(m)
    raw=source.read_bytes();m.load_segments(raw);names=m.rebase(source,raw)
    literal=b'Still waiting for root device\n\0';offset=raw.index(literal)
    assert raw.count(literal)==1
    message=next(base+offset-fo for base,vs,fo,fs in m.SEGMENTS if fo<=offset and offset+len(literal)<=fo+fs)
    target=names['_IOLog'];hits=[]
    for base,vs,fo,fs in m.SEGMENTS:
        for off in range(fo,fo+fs-12,4):
            a,b,c=struct.unpack_from('<III',raw,off)
            if a&0x9f00001f!=0x90000000 or b&0xffc003ff!=0x91000000 or c>>26!=0x25:continue
            pc=base+off-fo;imm=((a>>5)&0x7ffff)<<2|((a>>29)&3);imm=imm-(1<<21) if imm&(1<<20) else imm
            address=(pc&~4095)+(imm<<12)+((b>>10)&4095)
            branch=c&0x3ffffff;branch=branch-(1<<26) if branch&(1<<25) else branch
            if address==message and pc+8+branch*4==target:hits.append(pc+8)
    assert len(hits)==1,hits
    site=hits[0];data=bytearray(kernel.read_bytes())
    start=(int(panic['entry_va'],16)+panic['injected_bytes']+15)&~15
    assert not any(data[m.file_offset(start):m.file_offset(m.PANIC_CAVE_END)])
    with tempfile.TemporaryDirectory() as tmp:
        code,load,entry=m.assemble_c(ROOT/'device/early/root-wait-band.c',start,Path(tmp),names)
        wrapper=(load+len(code)+3)&~3
        asm='.text\n.global _start\n_start:\n stp x0,x30,[sp,#-16]!\n bl marker\n ldp x0,x30,[sp],#16\n b original\n'
        shim=m.assemble(asm,wrapper,{'marker':entry,'original':target},Path(tmp))
    assert wrapper+len(shim)<=m.PANIC_CAVE_END,f'Root marker exceeds checked padding ({len(code)}+{len(shim)} bytes)'
    assert len(shim)==16 and struct.unpack_from('<I',shim,12)[0]==m.branch(wrapper+12,target)
    assert data[m.file_offset(site):m.file_offset(site)+4]==raw[m.file_offset(site):m.file_offset(site)+4]
    data[m.file_offset(load):m.file_offset(load)+len(code)]=code
    data[m.file_offset(wrapper):m.file_offset(wrapper)+len(shim)]=shim
    struct.pack_into('<I',data,m.file_offset(site),0x94000000 | (m.branch(site,wrapper)&0x3ffffff))
    kernel.write_bytes(data)
    return {'log_message':literal[:-1].decode(),'message_va':hex(message),'original_IOLog_va':hex(target),
            'hook_call_va':hex(site),'marker_entry_va':hex(entry),'wrapper_va':hex(wrapper),
            'after_marker_tail_branch_va':hex(wrapper+12),'marker_bytes':len(code),'wrapper_bytes':len(shim),
            'normal_automatic_reset':False,'original_log_preserved':True,'scope':'Cyan fourth band on genuine root-wait log; not proof root filesystem mounted'}
