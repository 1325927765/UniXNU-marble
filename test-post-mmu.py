#!/usr/bin/env python3
"""Observe the exact post-MMU diagnostic at PSCI SMC in QEMU, never on a phone."""
import re
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

ROOT=Path(__file__).resolve().parent

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--vm-init',action='store_true')
    parser.add_argument("--timer",action="store_true")
    parser.add_argument("--machine-startup",action="store_true")
    parser.add_argument("--checkpoint",choices=['serial-init','console-init','dt-panic-console','dt-panic-timer','dt-panic-machine','dt-panic-vm-bootstrap','dt-panic-idle','dt-panic-cpu','dt-panic-opcode','vtimer-timer'])
    args=parser.parse_args()
    timer_probe=args.timer or args.checkpoint in ("dt-panic-timer","vtimer-timer")
    if sum([args.vm_init,args.timer,args.machine_startup,bool(args.checkpoint)])>1:parser.error("Choose one diagnostic profile")
    output=ROOT/'research/qemu-machine-startup-20261023' if args.machine_startup else (ROOT/('research/qemu-timer-20261023' if args.timer else ('research/qemu-vm-init-20261023' if args.vm_init else 'research/qemu-post-mmu-20261023')))
    if args.checkpoint:output=ROOT/('research/qemu-'+args.checkpoint+'-20261023')
    output.mkdir(parents=True,exist_ok=True)
    out=ROOT/'out/UNTESTED-marble-xnu-machine-startup' if args.machine_startup else (ROOT/('out/UNTESTED-marble-xnu-timer' if args.timer else ('out/UNTESTED-marble-xnu-vm-init' if args.vm_init else 'out/UNTESTED-marble-xnu-post-mmu')))
    if args.checkpoint:out=ROOT/('out/UNTESTED-marble-xnu-'+args.checkpoint)
    meta=json.loads((out/'kernel-probe.json').read_text())
    kernel=out/'marble-entry-probe-kernel.macho'
    assert hashlib.sha256(kernel.read_bytes()).hexdigest()==meta['instrumented_kernel_sha256']
    esp=output/'esp'
    shutil.copytree(ROOT/'research/qemu-xnu-entry-probe-20261023/esp',esp,dirs_exist_ok=True)
    shutil.copyfile(kernel,esp/'EFI/UniXNU/Payloads/kernel.macho')
    # This checkpoint runs in the identity-mapped physical alias, before arm_init_tramp.
    # The QEMU fixture allocates this fixed kernel PA; verify it against the loader log below.
    qemu_kernel_pa=0x48004000
    qemu_kernel_va=0xfffffff007004000
    checkpoint=qemu_kernel_pa+int(meta['post_mmu_reset_smc_va'],16)-qemu_kernel_va
    cave=qemu_kernel_pa+int(meta['post_mmu_cave_va'],16)-qemu_kernel_va
    if args.vm_init or args.timer or args.machine_startup or args.checkpoint:
        checkpoint=int(meta['post_mmu_reset_smc_va'],16)
        cave=int(meta['post_mmu_cave_va'],16)
    command=[sys.executable,ROOT/'sources/UniXNU/scripts/qemu-entry/gdb-stop.py',hex(checkpoint),
             '--fixture',output,'--esp',esp,'--kernel',kernel,'--firmware','/usr/share/AAVMF/AAVMF_CODE.fd',
             '--system-registers','--gic-version','3','--qemu-ramfb','--capture-screen','--timeout','45',
             '--trace-address',hex(cave)]
    requests={}
    if timer_probe:
        # Resolve globals from this exact instrumented Mach-O, not another build's symbol export.
        symbol_text=subprocess.check_output(['llvm-nm','-n',kernel],text=True)
        symbols={m[2]:int(m[1],16) for m in re.finditer(r'^([0-9a-fA-F]+)\s+\S\s+(\S+)$',symbol_text,re.M)}
        for name,size in {'_source_corecrypto14_status':4,'_prng_ready':4,'_armcpu_registered':4,'_armcpu_gic_ready':4,'_armcpu_timer_interrupts':8}.items():
            requests[name]=f'{symbols[name]:x}:{size:x}'
            command+=['--read-memory',requests[name]]
    with (output/'observer.log').open('w') as log:
        result=subprocess.run(command,stdout=log,stderr=subprocess.STDOUT)
    if result.returncode:
        print((output/'observer.log').read_text()[-5000:]);raise SystemExit(result.returncode)
    gdb=json.loads((output/'gdb-stop.json').read_text())
    regs={k:int(v,16) for k,v in gdb['system_registers'].items()}
    reached=int(gdb['pc'],16)==checkpoint
    mmu4k=bool(regs['SCTLR_EL1']&1) and (regs['TCR_EL1']>>14)&3==0 and (regs['TCR_EL1']>>30)&3==2
    mmu4k=bool(mmu4k and regs['TTBR0_EL1'] and regs['TTBR1_EL1'])
    call_ok=int(gdb['x0'],16)==0x84000009 and all(int(gdb[f'x{i}'],16)==0 for i in (1,2,3))
    uart=(output/'gdb-uart.log').read_text(errors='replace')
    assert 'va=0xFFFFFFF007004000 pa=0x48004000' in uart,'QEMU fixture kernel allocation changed'
    report={'checkpoint_pc':hex(checkpoint),'checkpoint_alias':(('canonical call boundary before '+meta['reset_before']) if meta.get('reset_before_call') else ('canonical address after '+meta['reset_after'])) if args.checkpoint else 'canonical address after machine_conf, before kernel_bootstrap' if args.machine_startup else 'canonical kernel virtual address inside real rtclock interrupt' if args.timer else ('canonical kernel virtual address after arm_vm_init return' if args.vm_init else 'identity-mapped physical alias before arm_init_tramp'),'scope':'Exact diagnostic kernel in QEMU; stopped before issuing SMC, no phone execution',
            'kernel_sha256':meta['instrumented_kernel_sha256'],'checkpoint_reached':reached,
            'active_4k_mmu_observed':mmu4k,'psci_system_reset_arguments_valid':call_ok,
            'system_registers':gdb['system_registers'],'counter_hz_qemu':regs['CNTFRQ_EL0'],
            'delay_ticks':19200000*6,'delay_seconds_on_confirmed_marble_counter':6,
            'delay_seconds_on_qemu_counter':19200000*6/regs['CNTFRQ_EL0'],
            'uefi_handoff_observed':'DARWINBOOT: inputs validated; exiting boot services' in uart,
            'normal_boot_intentionally_stopped_before_c_initialization':not (args.vm_init or args.timer or args.machine_startup or args.checkpoint),
            'machine_conf_returned':reached if args.machine_startup else None,
            'arm_vm_init_return_checkpoint_selected':args.vm_init,
            'arm_vm_init_returned':reached if args.vm_init else None,
            'hardware_boot_tested':False,'pass':reached and mmu4k and call_ok}
    if timer_probe:
        actual={name:int.from_bytes(bytes.fromhex(gdb['memory'][request]),'little') for name,request in requests.items()}
        report['globals']=actual
        report['real_timer_interrupt_observed']=reached and actual['_armcpu_timer_interrupts']>0 and actual['_armcpu_gic_ready']==1
        report['pass']=report['pass'] and report['real_timer_interrupt_observed'] and actual['_source_corecrypto14_status']==0 and actual['_prng_ready']==1 and actual['_armcpu_registered']==1
    if args.checkpoint:
        report['checkpoint_name']=args.checkpoint
        report['selected_call_returned']=reached and not meta.get('reset_before_call',False)
        report['selected_call_boundary_reached']=reached
        if meta.get('reset_before_call'):
            report['root_search_call_executed']=False
            report['root_device_discovery_ready_to_call']=reached
    (output/'result.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))
    if not report['pass']:raise SystemExit(1)

if __name__=='__main__':main()
