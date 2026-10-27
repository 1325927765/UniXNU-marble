#!/usr/bin/env python3
"""Tie the filmed CNTP UNDEF to the old opcode and audit its source rebuild."""
from pathlib import Path
import hashlib,importlib.util,json,re,shutil,struct,subprocess
ROOT=Path(__file__).resolve().parent

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def symbols(p):
    text=subprocess.check_output(['llvm-nm','-n',p],text=True)
    return {m[2]:int(m[1],16) for m in re.finditer(r'^([0-9a-fA-F]+)\s+\S\s+(\S+)$',text,re.M)}
def body(p):
    names=symbols(p);start=names['_fiq_context_init'];end=min(v for v in names.values() if v>start)
    assert end-start<1024
    return subprocess.check_output(['llvm-objdump','-d',f'--start-address={start:#x}',f'--stop-address={end:#x}',p],text=True)

def main():
    d=ROOT/'research/mac-virtual-timer-only-20261023'
    raw=d/'marble-early-source-kernel.macho';report=json.loads((d/'build-report.json').read_text())
    assert report['kernel_built'] and report['dt_panic_region_required'] and report['marble_virtual_timer_only_patch_requested']
    assert sha(raw)==report['kernel_sha256']
    patch=ROOT/'mac-build/patches/marble-virtual-timer-only.patch'
    assert sha(patch)==report['local_patch_overlay']['marble_virtual_timer_only']['sha256']
    old=ROOT/'out/UNTESTED-marble-xnu-dt-panic/marble-early-source-kernel.macho'
    assert sha(old)=='54af8e32e7386fa237c1b4d9c4f7d8533edf129bcc6d870ce6bc4ad8e76a3f6c'
    probe=ROOT/'research/entry-probe-source/scripts/patch-xnu-entry-probe.py'
    spec=importlib.util.spec_from_file_location('probe',probe);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
    data=old.read_bytes();m.load_segments(data)
    assert struct.unpack_from('<I',data,m.file_offset(0xfffffff007401dd8))[0]==0xd51be228
    before=body(old);after=body(raw)
    assert re.search(r'\bmsr\s+CNTP_CTL_EL0',before)
    assert re.search(r'\bmsr\s+CNTV_CTL_EL0',after)
    assert not re.search(r'\bmsr\s+CNTP_CTL_EL0',after)
    assert not re.search(r'\bnop\b',after),'Require a source rebuild, not an instruction NOP patch'
    src=(d/'machine_routines.c').read_text();part=src.split('_enable_virtual_timer(void)',1)[1].split('\n}',1)[0]
    assert '__builtin_arm_wsr64("CNTV_CTL_EL0", cntvctl);' in part
    assert '__builtin_arm_wsr64("CNTP_CTL_EL0"' not in part
    record=json.loads((d/'pe_init.o.json').read_text().strip().rstrip(','));args=record['arguments']
    assert '-DXNU_DT_PANIC_REGION=1' in args or any(a=='-D' and b=='XNU_DT_PANIC_REGION=1' for a,b in zip(args,args[1:]))
    (d/'fiq-before.S.txt').write_text(before);(d/'fiq-after.S.txt').write_text(after)
    out=ROOT/'out/UNTESTED-marble-xnu-virtual-timer-only';out.mkdir(parents=True,exist_ok=True)
    initial=d/'initial-build-report.json'
    if not initial.exists():shutil.copyfile(d/'build-report.json',initial)
    report.update(dt_panic_region_compile_verified=True,virtual_timer_only_compile_verified=True,
                  inaccessible_physical_timer_write_removed=True,virtual_timer_enable_retained=True,
                  source_patch_sha256=sha(patch),old_kernel_unchanged=True,selftests_disabled=False,
                  hardware_fault_PC='0xfffffff007401dd8',hardware_fault_opcode='0xd51be228',
                  fix_hardware_verified=False)
    (d/'build-report.json').write_text(json.dumps(report,indent=2)+'\n')
    shutil.copyfile(raw,out/raw.name);shutil.copyfile(d/'build-report.json',out/'build-report.json')
    print(json.dumps({'kernel_sha256':sha(raw),'virtual_timer_enable_retained':True,
                      'physical_timer_write_removed':True,'dt_panic_fix_retained':True,
                      'original_source_unchanged':True,'pass':True},indent=2))

if __name__=='__main__':main()
