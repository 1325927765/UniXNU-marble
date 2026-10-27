#!/usr/bin/env python3
"""QEMU only: inject a call to each patched panic ABI after real boot progress."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT=Path(__file__).resolve().parent
OBSERVER=ROOT/'sources/UniXNU/scripts/qemu-entry/gdb-stop.py'

def observer_wrapper():
    # Keep the pinned observer pristine. Add a test-only action while it is paused.
    text=OBSERVER.read_text()
    anchor="            report = {f'x{i}': hex(value) for i, value in enumerate(values[:31])}"
    assert text.count(anchor)==1
    injected='''            plan=json.loads(os.environ['MARBLE_PANIC_TEST_PLAN'])
            assert not interrupted and values[32]==args.address
            assert packet(f'z1,{args.address:x},4')=='OK'
            assert packet(f"Z1,{plan['reset']:x},4")=='OK'
            extra=[]
            if 'argument_slots' in plan:
                slotbase=(values[31]-128)&~15
                raw=b''.join(v.to_bytes(8,'little') for v in plan['argument_slots'])
                assert packet(f'M{slotbase:x},{len(raw):x}:{raw.hex()}')=='OK'
                extra.append((31,slotbase))
                if plan['common']:
                    # Deliberately different SP slots: common ABI must follow va_list *, not SP.
                    poison=(0x1111111111111111).to_bytes(8,'little')+(0x2222222222222222).to_bytes(8,'little')
                    assert packet(f'M{slotbase-64:x},10:{poison.hex()}')=='OK'
                    extra[-1]=(31,slotbase-64)
                    pointer=slotbase+32
                    assert packet(f'M{pointer:x},8:{slotbase.to_bytes(8,"little").hex()}')=='OK'
                    extra.append((1,pointer))
            for reg,value in [(0,plan['format']),(32,plan['entry'])]+extra:
                assert packet(f'P{reg:x}={value.to_bytes(8,"little").hex()}')=='OK'
            connection.settimeout(30)
            stop=packet('c')
            values=struct.unpack_from('<33Q',bytes.fromhex(packet('g')))
            interrupted=False
            assert values[32]==plan['reset'], f"Panic reset not reached: {values[32]:#x}"
'''
    text=text.replace(anchor,injected+anchor)
    sys.path.insert(0,str(OBSERVER.parent))
    exec(compile(text,str(OBSERVER),'exec'),{'__name__':'__main__','__file__':str(OBSERVER),'os':os})

def main():
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--checkpoint',choices=['dt-panic-idle','dt-panic-cpu','dt-panic-opcode','vtimer-timer','vtimer-wait'],default='dt-panic-idle')
    parser.add_argument('--entry',choices=['_panic','_panic_trap_to_debugger'])
    args=parser.parse_args()
    out=ROOT/('out/UNTESTED-marble-xnu-'+args.checkpoint)
    kernel=out/'marble-entry-probe-kernel.macho'
    meta=json.loads((out/'kernel-probe.json').read_text())
    assert hashlib.sha256(kernel.read_bytes()).hexdigest()==meta['instrumented_kernel_sha256']
    # Use real kernel read-only text as the raw format input, not an invented pointer.
    import importlib.util
    p=ROOT/'research/entry-probe-source/scripts/patch-xnu-entry-probe.py'
    spec=importlib.util.spec_from_file_location('probe',p);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
    blob=kernel.read_bytes();m.load_segments(blob)
    needle=(b'Undefined kernel instruction: pc=%p instr=%x @%s:%d\0' if args.checkpoint in ('dt-panic-opcode','vtimer-timer','vtimer-wait') else b'Platform Expert not initialized @%s:%d\0');offset=blob.index(needle)
    fmt=next(base+offset-fileoff for base,size,fileoff,filesize in m.SEGMENTS if fileoff<=offset and offset+len(needle)<=fileoff+filesize)
    results={}
    for name,entry in meta['panic_witness']['hooks'].items():
        if args.entry and name!=args.entry:continue
        dest=ROOT/('research/qemu-compact-panic-'+args.checkpoint+'-'+name.strip('_')+'-20261023')
        dest.mkdir(parents=True,exist_ok=True)
        esp=dest/'esp';shutil.copytree(ROOT/('research/qemu-'+args.checkpoint+'-20261023/esp'),esp,dirs_exist_ok=True)
        plan={'entry':int(entry,16),'reset':int(meta['panic_witness']['reset_smc_va'],16),'format':fmt}
        if args.checkpoint in ('dt-panic-opcode','vtimer-timer','vtimer-wait'):plan.update(argument_slots=[0xfffffff012345678,0xdeadbeef],common=name=='_panic_trap_to_debugger')
        primary=meta.get('post_mmu_reset_smc_va')
        if args.checkpoint=='vtimer-wait':
            import re
            nm=subprocess.check_output(['llvm-nm','-n',kernel],text=True)
            primary=next('0x'+m[1] for m in re.finditer(r'^([0-9a-fA-F]+)\s+\S\s+_rtclock_intr$',nm,re.M))
        command=[sys.executable,Path(__file__).resolve(),'--observer',primary,
                 '--fixture',dest,'--esp',esp,'--kernel',kernel,'--firmware','/usr/share/AAVMF/AAVMF_CODE.fd',
                 '--gic-version','3','--qemu-ramfb','--capture-screen','--timeout','45']
        with (dest/'observer.log').open('w') as log:
            subprocess.run(command,env=dict(os.environ,MARBLE_PANIC_TEST_PLAN=json.dumps(plan)),stdout=log,stderr=subprocess.STDOUT,check=True)
        g=json.loads((dest/'gdb-stop.json').read_text())
        valid=int(g['pc'],16)==plan['reset'] and int(g['x0'],16)==0x84000009 and all(int(g['x'+str(i)],16)==0 for i in (1,2,3))
        result={'test_only_intentional_panic_injection':True,'not_a_hardware_failure':True,'entry':name,
                'raw_format':needle[:-1].decode(),'kernel_sha256':meta['instrumented_kernel_sha256'],
                'panic_reset_checkpoint_reached':valid,'psci_system_reset_arguments_valid':valid,
                'scope':'Real diagnostic kernel booted to selected checkpoint in QEMU, then PC and x0 intentionally set to exercise patched panic entry; stopped before reset SMC',
                'screen_visual_review_required':True,'pass':valid}
        if 'argument_slots' in plan:result['injected_argument_slots']=[hex(v) for v in plan['argument_slots']];result['common_SP_slots_deliberately_different']=plan['common']
        (dest/'result.json').write_text(json.dumps(result,indent=2)+'\n');results[name]=result
        assert valid
    (ROOT/('research/compact-panic-tests-'+args.checkpoint+'.json')).write_text(json.dumps(results,indent=2)+'\n')
    print(json.dumps(results,indent=2))

if __name__=='__main__':
    if len(sys.argv)>1 and sys.argv[1]=='--observer':
        del sys.argv[1];observer_wrapper()
    else:main()
