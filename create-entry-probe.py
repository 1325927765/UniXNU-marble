#!/usr/bin/env python3
"""Instrument a copy of the real source kernel with checked upstream probes."""
import argparse
import importlib.util
import struct
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT=Path(__file__).resolve().parent


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--post-mmu",action="store_true",help="Stop after MMU with a delayed PSCI reset witness")
    parser.add_argument("--vm-init",action="store_true",help="Reset after arm_vm_init returns in arm_init")
    parser.add_argument("--timer",action="store_true",help="Reset only inside the real rtclock interrupt path")
    parser.add_argument("--machine-startup",action="store_true",help="Reset after machine_conf inside machine_startup, before kernel_bootstrap")
    parser.add_argument("--checkpoint",choices=['serial-init','console-init','dt-panic-console','dt-panic-timer','dt-panic-machine','dt-panic-vm-bootstrap','dt-panic-idle','dt-panic-cpu','dt-panic-opcode','vtimer-timer','vtimer-wait'])
    args=parser.parse_args()
    if sum([args.post_mmu,args.vm_init,args.timer,args.machine_startup,bool(args.checkpoint)])>1:parser.error("Choose one diagnostic profile")
    reset_probe=args.post_mmu or args.vm_init or args.timer or args.machine_startup or bool(args.checkpoint and args.checkpoint!='vtimer-wait')
    source=ROOT/'out/UNTESTED-marble-early-xnu/marble-early-source-kernel.macho'
    audit=json.loads((ROOT/'research/mac-build-20261023/build-report.json').read_text())
    if args.checkpoint and args.checkpoint.startswith('dt-panic-'):
        source=ROOT/'out/UNTESTED-marble-xnu-dt-panic/marble-early-source-kernel.macho'
        audit=json.loads((ROOT/'research/mac-dt-panic-20261023/build-report.json').read_text())
        assert audit['dt_panic_region_compile_verified']
    if args.checkpoint and args.checkpoint.startswith('vtimer-'):
        source=ROOT/'out/UNTESTED-marble-xnu-virtual-timer-only/marble-early-source-kernel.macho'
        audit=json.loads((ROOT/'research/mac-virtual-timer-only-20261023/build-report.json').read_text())
        assert audit['dt_panic_region_compile_verified'] and audit['virtual_timer_only_compile_verified']
    assert sha(source)==audit['kernel_sha256']
    upstream=ROOT/'research/entry-probe-source'
    provenance=json.loads((upstream/'provenance.json').read_text())
    for name,pin in provenance['files'].items():assert sha(upstream/name)==pin['sha256'],name
    out=ROOT/'out/UNTESTED-marble-xnu-machine-startup' if args.machine_startup else (ROOT/('out/UNTESTED-marble-xnu-timer' if args.timer else ('out/UNTESTED-marble-xnu-vm-init' if args.vm_init else ('out/UNTESTED-marble-xnu-post-mmu' if args.post_mmu else 'out/UNTESTED-marble-xnu-entry-probe'))))
    if args.checkpoint:out=ROOT/('out/UNTESTED-marble-xnu-'+args.checkpoint)
    out.mkdir(parents=True,exist_ok=True)
    kernel=out/'marble-entry-probe-kernel.macho'
    shutil.copyfile(source,kernel)
    env=dict(os.environ,UNIXNU_UEFI=str(ROOT/'sources/Mu-Silicium-marble'))
    with (out/'patch.log').open('w') as log:
        command=[sys.executable,upstream/'scripts/patch-xnu-entry-probe.py',kernel,*(['--reset-delay','6','--reset-after','_machine_conf','--in','_machine_startup'] if args.machine_startup else (['--reset-delay','6','--reset-after','_current_act','--in','_rtclock_intr'] if args.timer else (['--reset-delay','6','--reset-after','_arm_vm_init'] if args.vm_init else (['--reset-delay','6'] if args.post_mmu else ['--no-reset','--panic-screen']))))]
        if args.checkpoint and args.checkpoint!='vtimer-wait':
            callee={'serial-init':'_serial_init','console-init':'_PE_create_console','dt-panic-console':'_PE_create_console','dt-panic-timer':'_current_act','dt-panic-machine':'_machine_conf','dt-panic-vm-bootstrap':'_vm_mem_bootstrap','dt-panic-idle':'_cpu_machine_idle_init','dt-panic-cpu':'_fiq_context_init','dt-panic-opcode':'_fiq_context_init','vtimer-timer':'_current_act','vtimer-wait':'_IOLog'}[args.checkpoint]
            command=[sys.executable,upstream/'scripts/patch-xnu-entry-probe.py',kernel,'--reset-delay','6','--reset-after',callee,'--in',({'dt-panic-timer':'_rtclock_intr','vtimer-timer':'_rtclock_intr','dt-panic-machine':'_machine_startup','dt-panic-vm-bootstrap':'_kernel_bootstrap'}.get(args.checkpoint,'_arm_init'))]
        if args.checkpoint=='vtimer-wait':command=[sys.executable,upstream/'scripts/patch-xnu-entry-probe.py',kernel,'--no-reset']
        subprocess.run(command,
                       check=True,env=env,stdout=log,stderr=subprocess.STDOUT)
    panic_witness=None
    if args.checkpoint in ('dt-panic-idle','dt-panic-cpu','dt-panic-opcode','vtimer-timer','vtimer-wait'):
        spec=importlib.util.spec_from_file_location('compact_panic',ROOT/'add-compact-panic.py')
        compact=importlib.util.module_from_spec(spec);spec.loader.exec_module(compact)
        panic_witness=compact.add(kernel,source,registers=args.checkpoint in ('dt-panic-opcode','vtimer-timer','vtimer-wait'),after_stage=2 if args.checkpoint=='vtimer-wait' else 4)
    root_wait=None
    if args.checkpoint=='vtimer-wait':
        spec=importlib.util.spec_from_file_location('root_wait',ROOT/'add-root-wait-band.py')
        mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
        root_wait=mod.add(kernel,source,panic_witness)
    # Patching the actual text changes the source crypto POST input. Populate
    # its normal integrity field again; no selftest or check is disabled.
    subprocess.run([sys.executable,ROOT/'sources/UniXNU/scripts/seal-source-crypto-kernel.py',kernel],check=True)
    if args.checkpoint and args.checkpoint.startswith('vtimer-'):
        source=ROOT/'out/UNTESTED-marble-xnu-virtual-timer-only/marble-early-source-kernel.macho'
        audit=json.loads((ROOT/'research/mac-virtual-timer-only-20261023/build-report.json').read_text())
        assert audit['dt_panic_region_compile_verified'] and audit['virtual_timer_only_compile_verified']
    assert sha(source)==audit['kernel_sha256'],'Original source kernel was modified'
    report={'original_kernel_sha256':sha(source),'instrumented_kernel_sha256':sha(kernel),
            'upstream_provenance':provenance,'original_kernel_unchanged':True,
            'source_crypto_post_hmac_recomputed':True,'selftests_disabled':False,
            'automatic_reset':reset_probe,'reset_delay_seconds':6 if reset_probe else None,'counter_hz_for_reset':19200000 if reset_probe else None,'panic_function_redirected_to_visible_stop':not reset_probe,
            'scope':'Diagnostic copy, not an ordinary production kernel',
            'markers':{'green':'DarwinBoot stub before cache flush/MMU shutdown/branch',
                       'blue':'Actual XNU entry code executed (MMU initially off)',
                       'magenta':'XNU reached immediately before SCTLR_EL1 MMU enable; does not prove completion'},
            'hardware_boot_tested':False}
    if reset_probe:
        spec=importlib.util.spec_from_file_location('entry_probe',upstream/'scripts/patch-xnu-entry-probe.py')
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        original=source.read_bytes();module.load_segments(original);module.rebase(source,original)
        stage=4 if args.vm_init or args.timer or args.machine_startup or args.checkpoint else 3
        blob=kernel.read_bytes();at=module.file_offset(module.CAVES[stage]);chunk=blob[at:at+module.CAVE_SIZE]
        hits=[i for i in range(0,len(chunk),4) if chunk[i:i+4]==struct.pack('<I',0xd4000003)]
        assert len(hits)==1
        report['post_mmu_reset_smc_va']=hex(module.CAVES[stage]+hits[0])
        report['post_mmu_cave_va']=hex(module.CAVES[stage])
        report['markers']['post_mmu']='Counter-based 6 second delay followed by PSCI SYSTEM_RESET; stops ordinary boot at this checkpoint'
    if args.vm_init:
        report['reset_after']='_arm_vm_init'
        report['reset_in_function']='_arm_init'
        report['markers']['post_mmu']='Counter-based 6 second delay only after arm_vm_init returns; intentionally stops normal boot there'
    if args.timer:
        report['reset_after']='_current_act'
        report['callee_alias']='_current_act and _current_thread share VA 0xfffffff0073ffe08 in this exact kernel'
        report['reset_in_function']='_rtclock_intr'
        report['markers']['post_mmu']='Counter-based 6 second delay only after current_thread returns inside rtclock_intr; stops in interrupt context'
    if args.machine_startup:
        report['reset_after']='_machine_conf'
        report['reset_in_function']='_machine_startup'
        report['markers']['post_mmu']='Counter-based 6 second reset only after machine_conf returns; stops before kernel_bootstrap'
    if args.checkpoint:
        report['checkpoint_name']=args.checkpoint
        report['reset_after']={'serial-init':'_serial_init','console-init':'_PE_create_console','dt-panic-console':'_PE_create_console','dt-panic-timer':'_current_act','dt-panic-machine':'_machine_conf','dt-panic-vm-bootstrap':'_vm_mem_bootstrap','dt-panic-idle':'_cpu_machine_idle_init','dt-panic-cpu':'_fiq_context_init','dt-panic-opcode':'_fiq_context_init','vtimer-timer':'_current_act','vtimer-wait':'_IOLog'}[args.checkpoint]
        report['reset_in_function']={'dt-panic-timer':'_rtclock_intr','vtimer-timer':'_rtclock_intr','dt-panic-machine':'_machine_startup','dt-panic-vm-bootstrap':'_kernel_bootstrap'}.get(args.checkpoint,'_arm_init')
        report['markers']['post_mmu']='Counter-based 6 second reset only after '+report['reset_after']+' returns'
    if root_wait:
        report['root_wait_marker']=root_wait
        report['reset_after']=None
        report['reset_in_function']=None
        report['markers'].pop('post_mmu',None)
        report['normal_automatic_reset']=False
    if panic_witness:
        report['panic_witness']=panic_witness
        report['panic_function_redirected_to_visible_stop']=True
    (out/'kernel-probe.json').write_text(json.dumps(report,indent=2)+'\n')
    print((out/'patch.log').read_text())
    print(json.dumps(report,indent=2))


if __name__=='__main__':main()
