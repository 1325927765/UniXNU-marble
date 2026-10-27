#!/usr/bin/env python3
"""Observe a genuine source-built XNU milestone in QEMU; never phone evidence."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--kernel', type=Path, required=True)
    parser.add_argument('--symbols', type=Path, required=True, help='xcrun nm -U of the exact kernel')
    parser.add_argument('--uefi-run', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--checkpoint', default='_bsd_init')
    parser.add_argument('--timeout', type=int, default=90)
    args = parser.parse_args()
    if not 1 <= args.timeout <= 300:
        parser.error('--timeout must be 1..300 seconds')
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    symbols = {m[2]: int(m[1], 16) for m in re.finditer(r'^([0-9a-fA-F]+)\s+\S\s+(\S+)$', args.symbols.read_text(), re.M)}
    if args.checkpoint not in symbols or '_panic' not in symbols:
        parser.error('Requested checkpoint or panic symbol is missing')
    esp = output / 'esp'
    payload = esp / 'EFI/UniXNU/Payloads'
    payload.mkdir(parents=True, exist_ok=True)
    (esp / 'EFI/BOOT').mkdir(parents=True, exist_ok=True)
    shutil.copyfile(args.uefi_run / 'UniXNU.efi', esp / 'EFI/BOOT/BOOTAA64.EFI')
    shutil.copyfile(args.uefi_run / 'DarwinBoot.efi', payload / 'DarwinBoot.efi')
    shutil.copyfile(args.kernel, payload / 'kernel.macho')
    upstream = ROOT / 'sources/UniXNU'
    subprocess.run([sys.executable, upstream / 'scripts/qemu-entry/make-dt.py',
                    '--output', payload / 'kernel.macho.adt', '--owned-memory-size', '0x20000000',
                    '--dram-size', '0x40000000', '--armvirt', '--armcpu', '--nvram-proxy'], check=True)
    (esp / 'EFI/UniXNU/unixnu.toml').write_text('''version = 1
[boot]
timeout = 1
default = "source-xnu"
[kits]
autoload = false
[[driver]]
path = "Payloads/DarwinBoot.efi"
[[entry]]
id = "source-xnu"
title = "QEMU source XNU checkpoint"
type = "xnu"
path = "Payloads/kernel.macho"
args = "-v serial=3 debug=0x14e kt_fixed_zones=120"
''')
    observations = {
        '_page_shift': 4, '_vm_kernel_page_shift': 4,
        '_source_corecrypto14_status': 4, '_g_crypto_funcs': 8, '_prng_ready': 4,
        '_armdt_platform_configured': 4, '_armdt_platform_cpu_count': 4,
        '_armdt_platform_nvram_proxy': 4, '_armcpu_registered': 4,
        '_armcpu_gic_ready': 4, '_armcpu_timer_interrupts': 8,
    }
    requests = {name: f'{symbols[name]:x}:{size:x}' for name, size in observations.items() if name in symbols}
    command = [sys.executable, upstream / 'scripts/qemu-entry/gdb-stop.py', hex(symbols[args.checkpoint]),
               '--fixture', output, '--esp', esp, '--kernel', args.kernel,
               '--firmware', '/usr/share/AAVMF/AAVMF_CODE.fd', '--system-registers',
               '--gic-version', '3', '--qemu-ramfb', '--capture-screen', '--timeout', str(args.timeout),
               '--also-stop', hex(symbols['_panic'])]
    for name in ('_arm_init', '_kernel_bootstrap', '_source_corecrypto14_bootstrap'):
        if name in symbols and name != args.checkpoint:
            command += ['--trace-address', hex(symbols[name])]
    for request in requests.values():
        command += ['--read-memory', request]
    with (output / 'observer.log').open('w') as log:
        result = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT)
    if result.returncode:
        print((output / 'observer.log').read_text()[-5000:])
        raise SystemExit(result.returncode)
    report = json.loads((output / 'gdb-stop.json').read_text())
    actual = {name: int.from_bytes(bytes.fromhex(report['memory'][request]), 'little')
              for name, request in requests.items()}
    registers = {name: int(value, 16) for name, value in report['system_registers'].items()}
    tcr = registers['TCR_EL1']
    uart = (output / 'gdb-uart.log').read_text(errors='replace')
    reached = int(report['pc'], 16) == symbols[args.checkpoint]
    mmu4k = ((tcr >> 14) & 3) == 0 and ((tcr >> 30) & 3) == 2 and bool(registers['SCTLR_EL1'] & 1)
    mmu4k = mmu4k and bool(registers['TTBR0_EL1']) and bool(registers['TTBR1_EL1'])
    handoff = 'DARWINBOOT: inputs validated; exiting boot services' in uart and 'ASSERT' not in uart
    summary = {
        'scope': 'QEMU virt, single CPU; genuine source XNU; not marble hardware',
        'kernel_sha256': hashlib.sha256(args.kernel.read_bytes()).hexdigest(),
        'darwinboot_sha256': hashlib.sha256((payload / 'DarwinBoot.efi').read_bytes()).hexdigest(),
        'checkpoint': args.checkpoint, 'checkpoint_reached': reached,
        'uefi_handoff_observed': handoff, 'active_4k_mmu_observed': mmu4k,
        'globals': actual, 'marble_hardware_tested': False, 'userspace_booted': False,
        'pass': reached and handoff and mmu4k,
    }
    (output / 'result.json').write_text(json.dumps(summary, indent=2) + '\n')
    print(json.dumps(summary, indent=2))
    if not summary['pass']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
