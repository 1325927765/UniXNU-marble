#!/usr/bin/env python3
"""Observe real XNU md0/MockFS mount returns, including malformed-root refusal.

Offline QEMU fixture only. It supplies our own static executable, not iOS.
No guest register/return-value edits or filesystem authentication bypasses.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys

ROOT = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--invalid-header', action='store_true')
    parser.add_argument('--block-read', action='store_true', help='Observe the actual first md0 strategy request separately')
    parser.add_argument('--vfs-root', action='store_true', help='Observe completion of the outer VFS root mount')
    args = parser.parse_args()
    if args.block_read and (args.invalid_header or args.vfs_root):
        parser.error('Choose one observation')
    mode = 'block-read' if args.block_read else ('vfs-' if args.vfs_root else '') + ('invalid-header' if args.invalid_header else 'valid')
    out = ROOT / 'research/qemu-ram-root-20261023' / mode
    out.mkdir(parents=True, exist_ok=True)
    esp = out / 'esp'
    shutil.copytree(ROOT / 'research/qemu-vtimer-timer-20261023/esp', esp, dirs_exist_ok=True)
    payloads = esp / 'EFI/UniXNU/Payloads'
    kernel = ROOT / 'research/mac-ram-root-fixture-20261023/marble-early-source-kernel.macho'
    own = (ROOT / 'research/mac-native-user-fixture-20261023/launchd.macho').read_bytes()
    probe = b'Marble owned RAM root block I/O fixture\n'
    offset = (4096 + len(own) + 4095) & ~4095
    image = bytearray((offset + len(probe) + 4095) & ~4095)
    struct.pack_into('<8sII4Q', image, 0, b'N4KROOT\0', 1, 3 if args.invalid_header else 2,
                     4096, len(own), offset, len(probe))
    image[4096:4096+len(own)] = own
    image[offset:offset+len(probe)] = probe
    (payloads / 'ram-root-fixture.img').write_bytes(image)
    shutil.copyfile(kernel, payloads / 'kernel.macho')
    config = esp / 'EFI/UniXNU/unixnu.toml'
    config.write_text(config.read_text().replace('args = "-v',
        'initrd = "Payloads/ram-root-fixture.img"\nargs = "rd=md0 -v'))
    subprocess.run([sys.executable, ROOT / 'sources/UniXNU/scripts/qemu-entry/make-dt.py',
        '--output', payloads / 'kernel.macho.adt', '--dram-size', str(1024**3),
        '--owned-memory-size', '0x20000000', '--armvirt', '--armcpu', '--nvram-proxy', '--ramdisk'], check=True)
    nm = subprocess.check_output(['llvm-nm', '-n', kernel], text=True)
    names = {m[2]: int(m[1], 16) for m in re.finditer(r'^([0-9a-fA-F]+)\s+\S\s+(\S+)$', nm, re.M)}
    wanted = {'_rootdev': 4, '_rootdevice': 16, '_source_corecrypto14_status': 4,
              '_prng_ready': 4, '_armcpu_gic_ready': 4, '_armcpu_timer_interrupts': 8}
    requests = {n: f'{names[n]:x}:{size:x}' for n, size in wanted.items()}
    target_name = '_mdevstrategy' if args.block_read else '_vfs_mountroot' if args.vfs_root else '_mockfs_mountroot'
    target = names[target_name]
    command = [sys.executable, ROOT / 'sources/UniXNU/scripts/qemu-entry/gdb-stop.py',
        hex(target), '--fixture', out,
        '--esp', esp, '--kernel', kernel, '--firmware', '/usr/share/AAVMF/AAVMF_CODE.fd',
        '--system-registers', '--gic-version', '3', '--timeout', '90',
        '--also-stop', hex(names['_panic'])]
    if not args.block_read:
        command.append('--finish-function')
    # All traces precede the primary function; a pending trace breakpoint inside
    # that function would stop the observer before its real return.
    trace_names = {n: names[n] for n in (['_bsd_init'] if args.vfs_root else ['_bsd_init', '_vfs_mountroot']) if n in names}
    for address in trace_names.values():
        command += ['--trace-address', hex(address)]
    for request in requests.values():
        command += ['--read-memory', request]
    with (out / 'observer.log').open('w') as log:
        subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, check=True)
    observed = json.loads((out / 'gdb-stop.json').read_text())
    values = {n: int.from_bytes(bytes.fromhex(observed['memory'][request]), 'little')
              for n, request in requests.items() if n != '_rootdevice'}
    device = bytes.fromhex(observed['memory'][requests['_rootdevice']]).split(b'\0')[0].decode()
    result = int(observed['x0'], 16)
    # vfs_subr.c tries every root-capable filesystem. MockFS returns EINVAL
    # for this malformed header; after none accepts it, VFS returns ENODEV.
    expected = (19 if args.vfs_root else 22) if args.invalid_header else 0
    block_record = ROOT / 'research/qemu-ram-root-20261023/block-read/result.json'
    block_evidence = json.loads(block_record.read_text()) if block_record.exists() else None
    kernel_hash = hashlib.sha256(kernel.read_bytes()).hexdigest()
    block_io = (int(observed['pc'], 16) == target and not observed['bounded_timeout_interrupted']) if args.block_read else bool(
        block_evidence and block_evidence.get('pass') and block_evidence['genuine_memory_disk_io_observed']
        and block_evidence['kernel_sha256'] == kernel_hash)
    returned = observed.get('function_return_stack_matched', False)
    passed = bool(returned and result == expected and device == 'md0'
                  and values['_source_corecrypto14_status'] == 0 and values['_prng_ready'] == 1 and block_io)
    if args.block_read:
        passed = bool(block_io and device == 'md0' and values['_source_corecrypto14_status'] == 0
                      and values['_prng_ready'] == 1)
    report = {'pass': passed, 'mode': mode, 'observed_function': target_name,
        'actual_mount_return': None if args.block_read else result, 'expected_mount_return': None if args.block_read else expected,
        'root_device': device, 'genuine_memory_disk_io_observed': block_io,
        'mount_function_return_observed': returned,
        'root_filesystem_mounted': bool(args.vfs_root and returned and result == 0), 'globals': values,
        'kernel_sha256': kernel_hash,
        'root_image_sha256': hashlib.sha256(image).hexdigest(), 'root_image_bytes': len(image),
        'ios_userspace_boot_demonstrated': False, 'marble_hardware_tested': False,
        'scope': 'Real md0 block reads and public MockFS mount in QEMU. Own two-file fixture only; no APFS, UFS or Apple userspace.'}
    (out / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))
    if not passed:
        raise SystemExit('RAM root qualification failed; inspect the actual observation')


if __name__ == '__main__':
    main()
