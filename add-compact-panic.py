#!/usr/bin/env python3
"""Add a bounded panic witness to a diagnostic copy using checked empty padding."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import struct
import subprocess
import tempfile

ROOT=Path(__file__).resolve().parent

def add(kernel, source, registers=False, after_stage=4):
    script=ROOT/'research/entry-probe-source/scripts/patch-xnu-entry-probe.py'
    spec=importlib.util.spec_from_file_location('upstream_probe',script)
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
    raw=source.read_bytes();m.load_segments(raw);names=m.rebase(source,raw)
    data=bytearray(kernel.read_bytes())
    start=m.CAVES[after_stage]+m.CAVE_SIZE
    assert not any(data[m.file_offset(start):m.file_offset(m.PANIC_CAVE_END)])
    os.environ['UNIXNU_UEFI']=str(ROOT/'sources/Mu-Silicium-marble')
    c=ROOT/('device/early/compact-panic-registers.c' if registers else 'device/early/compact-panic.c')
    with tempfile.TemporaryDirectory() as tmp:
        code,load,entry=m.assemble_c(c,start,Path(tmp),names)
        symbols={line.split()[2]:int(line.split()[0],16)
                 for line in subprocess.check_output(['llvm-nm',Path(tmp)/'panic.elf'],text=True).splitlines()
                 if len(line.split())==3}
        assert load+len(code)<=m.PANIC_CAVE_END, f'Panic witness {len(code):#x} exceeds checked padding'
        if registers:
            main=symbols['panic_screen_main'];common=symbols['panic_screen_common']
            assert code[:12]==struct.pack('<III',0x910003e1,0xd2800002,m.branch(entry+8,main))
            at=common-load
            assert code[at:at+8]==struct.pack('<II',0xd2800022,m.branch(common+4,main))
        reset=symbols['panic_reset_checkpoint']
        assert code[reset-load:reset-load+4]==struct.pack('<I',0xd4000003)
    assert not any(data[m.file_offset(load):m.file_offset(load)+len(code)])
    data[m.file_offset(load):m.file_offset(load)+len(code)]=code
    hooks={}
    for name in ('_panic','_panic_trap_to_debugger'):
        va=names[name];at=m.file_offset(va)
        assert data[at:at+4]==raw[at:at+4] and int.from_bytes(data[at:at+4],'little') not in (0,0xffffffff)
        hooks[name]=hex(va)
        target=symbols['panic_screen_common'] if registers and name=='_panic_trap_to_debugger' else entry
        assert load<=target<load+len(code)
        struct.pack_into('<I',data,at,m.branch(va,target))
    kernel.write_bytes(data)
    return {'code_sha256':hashlib.sha256(c.read_bytes()).hexdigest(),'injected_bytes':len(code),
            'checked_padding_start':hex(start),'checked_padding_end':hex(m.PANIC_CAVE_END),
            'entry_va':hex(entry),'reset_smc_va':hex(reset),'hooks':hooks,
            'delay_seconds':12,'frequency_source':'CNTFRQ_EL0',
            'display':('Red area, bounded raw format, ARG0/ARG1, ESR/ELR; checked Darwin argument-slot reads' if registers else 'Fourth band red, PANIC and at most 96 raw format characters; no variadic argument reads'),
            'argument_slots_read':2 if registers else 0,
            'common_entry_va':hex(symbols['panic_screen_common']) if registers else hex(entry),
            'limits':'Requires working exception/stack state and existing framebuffer mapping; absence of red is inconclusive'}

if __name__=='__main__':
    import sys
    print(json.dumps(add(Path(sys.argv[1]),Path(sys.argv[2])),indent=2))
