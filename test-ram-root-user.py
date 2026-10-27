#!/usr/bin/env python3
"""Observe our own static process after an actual RAM root mount in QEMU.

This is a Darwin syscall instrument, not Apple's launchd or iOS userspace.
"""
import hashlib
import json
from pathlib import Path
import re
import struct
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
out = ROOT / 'research/qemu-ram-root-20261023/own-process'
out.mkdir(parents=True, exist_ok=True)
fixture = ROOT / 'research/mac-native-user-fixture-20261023'
addresses = json.loads((fixture / 'addresses.json').read_text())
mounted = json.loads((ROOT / 'research/qemu-ram-root-20261023/vfs-valid/result.json').read_text())
assert mounted['pass'] and mounted['root_filesystem_mounted']
kernel = ROOT / 'research/mac-ram-root-fixture-20261023/marble-early-source-kernel.macho'
assert hashlib.sha256(kernel.read_bytes()).hexdigest() == mounted['kernel_sha256']
nm = subprocess.check_output(['llvm-nm', '-n', kernel], text=True)
names = {m[2]: int(m[1], 16) for m in re.finditer(r'^([0-9a-fA-F]+)\s+\S\s+(\S+)$', nm, re.M)}
requests = {name: f'{addresses[name]:x}:{size:x}' for name, size in
            [('_results', 32), ('_user_page_size', 8), ('_old_length', 8)]}
requests['_amfi'] = f'{names["_amfi"]:x}:8'
command = [sys.executable, ROOT / 'sources/UniXNU/scripts/qemu-entry/gdb-stop.py',
    hex(addresses['_checkpoint']), '--fixture', out, '--esp',
    ROOT / 'research/qemu-ram-root-20261023/vfs-valid/esp', '--kernel', kernel,
    '--firmware', '/usr/share/AAVMF/AAVMF_CODE.fd', '--system-registers',
    '--gic-version', '3', '--timeout', '90', '--also-stop', hex(names['_panic'])]
for request in requests.values():
    command += ['--read-memory', request]
with (out / 'observer.log').open('w') as log:
    subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, check=True)
observed = json.loads((out / 'gdb-stop.json').read_text())
at_checkpoint = int(observed['pc'], 16) == addresses['_checkpoint'] and not observed['bounded_timeout_interrupted']
el0 = at_checkpoint and int(observed['pstate'], 16) & 15 == 0
syscalls = None
if el0:
    pid, result, pid_flags, sysctl_flags = struct.unpack('<4Q', bytes.fromhex(observed['memory'][requests['_results']]))
    syscalls = {'pid': pid, 'sysctl_return': result,
        'getpid_carry': (pid_flags >> 29) & 1, 'sysctl_carry': (sysctl_flags >> 29) & 1,
        'page_size': int.from_bytes(bytes.fromhex(observed['memory'][requests['_user_page_size']]), 'little'),
        'old_length': int.from_bytes(bytes.fromhex(observed['memory'][requests['_old_length']]), 'little')}
passed = bool(el0 and syscalls == {'pid': 1, 'sysctl_return': 0, 'getpid_carry': 0,
                                'sysctl_carry': 0, 'page_size': 4096, 'old_length': 4})
amfi = int.from_bytes(bytes.fromhex(observed['memory'][requests['_amfi']]), 'little')
fault_pc = int(observed['system_registers']['ELR_EL1'], 16)
missing_amfi = (amfi == 0 and names['_accelerate_entitlement_queries'] <= fault_pc <
                names['_accelerate_entitlement_queries'] + 0x50 and
                int(observed['system_registers']['FAR_EL1'], 16) == 0x1a0)
report = {'pass': passed, 'own_static_process_el0_observed': el0, 'actual_syscalls': syscalls,
    'kernel_sha256': mounted['kernel_sha256'], 'root_image_sha256': mounted['root_image_sha256'],
    'own_executable_sha256': hashlib.sha256((fixture / 'launchd.macho').read_bytes()).hexdigest(),
    'ios_userspace_boot_demonstrated': False, 'apple_launchd_executed': False,
    'amfi_pointer': hex(amfi), 'fault_pc': hex(fault_pc),
    'failure_stage': 'AMFI_entitlement_provider_missing' if missing_amfi else None,
    'marble_hardware_tested': False, 'scope': 'Own signed static Darwin process in md0/MockFS. No Apple userspace.'}
(out / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
print(json.dumps(report, indent=2))
if not passed:
    raise SystemExit('Own static EL0 instrument did not pass; inspect the actual stop')
