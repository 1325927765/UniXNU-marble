#!/usr/bin/env python3
"""Observe actual original iPhone iOS 16 components in a QEMU kernel.

The RAM root contains our own static process. It is not an Apple userspace boot.
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
    parser.add_argument('--candidate', type=Path, default=ROOT / 'research/mac-iphone16-20261023/iphone16-components-v1.macho')
    parser.add_argument('--checkpoint', choices=['bsd-init', 'amfi-register', 'vfs-root', 'mach-load', 'own-process', 'apple-dyld', 'apple-main'], default='bsd-init')
    parser.add_argument('--name', default='v1-bsd-init')
    parser.add_argument('--crypto-hash-method', choices=['sha2-384', 'sha1'])
    parser.add_argument('--unpersonalized-image4', action='store_true')
    parser.add_argument('--iphone-restore-root', action='store_true', help='Use the unchanged iPhone 20H392 restore APFS ramdisk instead of our MockFS fixture')
    parser.add_argument('--original-trust-cache', action='store_true', help='Hand off the unchanged original iPhone static v2 trust module')
    parser.add_argument('--mount-layout', type=Path, help='Actual compiler mount layout, qualified against this native kernel')
    parser.add_argument('--declare-qemu-vmm', action='store_true', help='Truthfully publish that this Linux dummy-virt fixture is running in QEMU')
    parser.add_argument('--user-syscall-log', action='store_true', help='Observe bounded original Darwin userspace syscalls, including real write buffers')
    parser.add_argument('--timeout', type=int, choices=[30, 45, 60, 120], default=60)
    parser.add_argument('--corrupt-dyld-page', action='store_true', help='Offline refusal control: corrupt one exact original dyld code-page copy in guest RAM before real signature validation')
    args = parser.parse_args()
    if args.iphone_restore_root and args.checkpoint == 'own-process':
        parser.error('The original restore root does not contain our static checkpoint process')
    if args.checkpoint.startswith('apple-') and not args.iphone_restore_root:
        parser.error('Apple userspace checkpoints require the pinned original iPhone restore root')
    if args.corrupt_dyld_page and (args.checkpoint != 'apple-dyld' or not args.declare_qemu_vmm):
        parser.error('Dyld page fault control requires the explicit QEMU dyld experiment')
    if not re.fullmatch(r'[a-z0-9-]{1,64}', args.name):
        parser.error('Invalid experiment name')
    kernel = args.candidate.resolve()
    plan = json.loads(kernel.with_suffix('.json').read_text())
    digest = hashlib.sha256(kernel.read_bytes()).hexdigest()
    assert digest == plan['candidate_sha256'] and not plan['register_dataflow_qualified']
    layout = json.loads(args.mount_layout.read_text()) if args.mount_layout else None
    if layout and layout['kernel_sha256'] != plan['native_sha256']:
        raise ValueError('Mount observer layout belongs to a different native kernel')
    out = ROOT / 'research/qemu-iphone16-20261023' / args.name
    out.mkdir(parents=True, exist_ok=True)
    esp = out / 'esp'
    shutil.copytree(ROOT / 'research/qemu-ram-root-20261023/vfs-valid/esp', esp, dirs_exist_ok=True)
    payload = esp / 'EFI/UniXNU/Payloads'
    shutil.copyfile(kernel, payload / 'kernel.macho')
    if args.original_trust_cache:
        module = (ROOT / 'research/iphone16-restore-input/087-86698-044.dmg.trustcache.module').read_bytes()
        if (len(module) != 66264 or struct.unpack_from('<I', module)[0] != 2 or
                hashlib.sha256(module).hexdigest() != 'b7ab28e0009900326ae685a88748008a9653e6bcbd70674135dac4eb5231ad64'):
            raise ValueError('Require the exact original static v2 trust module')
        (payload / 'kernel.macho.trustcache').write_bytes(struct.pack('<2I', 1, 8)+module)
    if args.iphone_restore_root:
        root_image = ROOT / 'research/iphone16-restore-input/iphone16-restore.dmg'
        root_data = root_image.read_bytes()
        if len(root_data) != 106954752 or hashlib.sha256(root_data).hexdigest() != 'd180c38dcc754bc079cc92a40f58a4b5fad2c2b7ce72cf5e64a117453fd7c90a':
            raise ValueError('Require the unchanged pinned original iPhone restore APFS payload')
        shutil.copyfile(root_image, payload / 'ram-root-fixture.img')
    if args.crypto_hash_method:
        subprocess.run([sys.executable, ROOT / 'sources/UniXNU/scripts/qemu-entry/make-dt.py',
            '--output', payload / 'kernel.macho.adt', '--dram-size', str(1024**3),
            '--owned-memory-size', '0x20000000', '--armvirt', '--armcpu', '--nvram-proxy',
            '--ramdisk', '--crypto-hash-method', args.crypto_hash_method,
            *(['--trust-cache'] if args.original_trust_cache else []),
            *(['--qemu-vmm-present'] if args.declare_qemu_vmm else []),
            *(['--osenvironment', 'ramdisk'] if args.iphone_restore_root else [])], check=True)
    if args.unpersonalized_image4:
        subprocess.run([sys.executable, ROOT / 'prepare-iphone16-qemu-adt.py', payload / 'kernel.macho.adt'], check=True)
    # Keep the exact successful public md0 fixture and memory ownership settings.
    nm = subprocess.check_output(['llvm-nm', '-n', kernel], text=True)
    names = {m[2]: int(m[1], 16) for m in re.finditer(r'^([0-9a-fA-F]+)\s+\S\s+(\S+)$', nm, re.M)}
    target_name = {'bsd-init': '_bsd_init', 'amfi-register': '_amfi_interface_register',
                   'vfs-root': '_vfs_mountroot', 'mach-load': '_load_machfile', 'own-process': '_checkpoint',
                   'apple-dyld': '_thread_setentrypoint', 'apple-main': '_thread_setentrypoint'}[args.checkpoint]
    own = json.loads((ROOT / 'research/mac-native-user-fixture-20261023/addresses.json').read_text())
    target = own[target_name] if args.checkpoint == 'own-process' else names[target_name]
    wanted = {'_g_crypto_funcs': 8, '_crypto_init': 1, '_prng_ready': 4, '_amfi': 8,
              '_mac_late': 4, '_armcpu_gic_ready': 4, '_armcpu_timer_interrupts': 8}
    for name, size in [('_trust_cache_rt', 8), ('_trust_cache_static_init', 1), ('_trust_cache_static_loaded', 1)]:
        if name in names:
            wanted[name] = size
    for name in ['_cs_validate_page_bad_hash', '_cs_validate_page_no_hash', '_cs_native4k_full_blocks',
                 '_cs_native4k_page_checks', '_cs_native4k_ready_blobs']:
        if name in names:
            wanted[name] = 8
    for name in ['_cs_system_enforcement_enable', '_cs_process_enforcement_enable',
                 '_cs_procs_killed', '_cs_procs_invalidated']:
        if name in names:
            wanted[name] = 8 if name in ['_cs_procs_killed', '_cs_procs_invalidated'] else 4
    for name in ['_native_aes_kat_status', '_native_aes_interface_status', '_native_aes_registered',
                 '_native_aes_completed', '_native_aes_unsupported_key']:
        if name in names:
            wanted[name] = 4
    for name in ['_marble_iphone16_crypto_status', '_marble_iphone16_crypto_calls', '_marble_iphone16_crypto_adoptions',
                 '_marble_iphone16_prng_deferred', '_marble_iphone16_prng_completed']:
        if name in names:
            wanted[name] = 4
    for name in ['_marble_iphone16_entropy_early_requests', '_marble_iphone16_entropy_lazy_initializations']:
        if name in names:
            wanted[name] = 4
    requests = {name: f'{names[name]:x}:{size:x}' for name, size in wanted.items()}
    boot = plan.get('iphone16_original_crypto_boot')
    if boot:
        requests['original_crypto_header'] = f'{int(boot["values"][4], 16):x}:600'
        requests['crypto_boot_descriptor'] = f'{int(boot["descriptor_va"], 16):x}:48'
    if args.checkpoint == 'own-process':
        requests.update({name: f'{own[name]:x}:{size:x}' for name, size in
                        [('_results', 32), ('_user_page_size', 8), ('_old_length', 8)]})
    command = [sys.executable, ROOT / 'sources/UniXNU/scripts/qemu-entry/gdb-stop.py',
        hex(target), '--fixture', out, '--esp', esp, '--kernel', kernel,
        '--firmware', '/usr/share/AAVMF/AAVMF_CODE.fd', '--system-registers',
        '--gic-version', '3', '--timeout', str(args.timeout), '--also-stop', hex(names['_panic'])]
    if args.user_syscall_log:
        command += ['--syscall-log-address', hex(names['_unix_syscall'])]
    if args.corrupt_dyld_page:
        original_dyld = (ROOT / 'research/iphone16-restore-input/userspace/dyld').read_bytes()
        if hashlib.sha256(original_dyld).hexdigest() != '5806834564fe6462ae981d0915d612b1eb2f6f168822b5d278bee56254933757':
            raise ValueError('Fault control requires the pinned original dyld')
        site = names['_cs_validate_hash']
        page_hash = hashlib.sha256(original_dyld[0x15000:0x16000]).hexdigest()
        command += ['--trace-address', hex(site), '--mutate-mapped-vnode-page', f'{site:x}:15000:200:{page_hash}']
        command += ['--read-followed-relative=-0x1b0:0x1000']
    if args.checkpoint in ['vfs-root', 'mach-load']:
        command.append('--finish-function')
    mount_request = None
    if layout:
        # The root mount is the first entry in the actual BSD mount list.
        # The legacy rootfs global is not populated on this configuration.
        mount_pointer = '_mountlist'
        mount_request = f'{names[mount_pointer]:x}:{layout["fstypename_offset"]:x}:{layout["fstypename_bytes"]:x}'
        command += ['--read-indirect', mount_request]
    if args.checkpoint.startswith('apple-'):
        command += ['--follow-entrypoint-arg', '1']
        if args.checkpoint == 'apple-main':
            command += ['--follow-main-entry-offset', '0x169b4']
        else:
            command += ['--step-followed-entry', '4']
    for request in requests.values():
        command += ['--read-memory', request]
    if args.checkpoint in ['bsd-init', 'amfi-register']:
        command += ['--trace-address', hex(names['_register_crypto_functions'])]
    with (out / 'observer.log').open('w') as log:
        subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, check=True)
    observed = json.loads((out / 'gdb-stop.json').read_text())
    mount_bytes = observed.get('indirect_memory', {}).get(mount_request, {}).get('bytes', '')
    filesystem = bytes.fromhex(mount_bytes).split(b'\0')[0].decode('ascii') if mount_bytes and not mount_bytes.startswith('E') else None
    values = {n: int.from_bytes(bytes.fromhex(observed['memory'][requests[n]]), 'little') for n in wanted}
    at_target = bool(observed.get('function_return_stack_matched')) if args.checkpoint in ['vfs-root', 'mach-load'] else (
        int(observed['pc'], 16) == target and not observed['bounded_timeout_interrupted'])
    user = observed.get('followed_user_entry', {})
    main_entry = observed.get('followed_main_entry', {})
    dyld_bytes_match = False
    main_bytes_match = False
    if user.get('observed'):
        dyld = (ROOT / 'research/iphone16-restore-input/userspace/dyld').read_bytes()
        if hashlib.sha256(dyld).hexdigest() != '5806834564fe6462ae981d0915d612b1eb2f6f168822b5d278bee56254933757':
            raise ValueError('Original dyld audit input differs')
        # This exact original MH_DYLINKER has __TEXT vmaddr/fileoff zero and
        # LC_UNIXTHREAD PC 0x151b0. Compare actual EL0 bytes after ASLR.
        dyld_bytes_match = user.get('entry_bytes') == dyld[0x151b0:0x151c0].hex()
        for step in user.get('steps', []):
            offset = int(step['pc'], 16) - int(user['user_entry'], 16) + 0x151b0
            dyld_bytes_match = dyld_bytes_match and step['bytes'] == dyld[offset:offset+16].hex()
    if main_entry.get('observed'):
        launchd = (ROOT / 'research/iphone16-restore-input/userspace/launchd').read_bytes()
        if hashlib.sha256(launchd).hexdigest() != '12370e5ee35bf28ae479b6c4b4455f4f4693ab803e37c5eb3032537c18cac61c':
            raise ValueError('Original launchd audit input differs')
        main_bytes_match = main_entry.get('entry_bytes') == launchd[0x169b4:0x169c4].hex()
    if args.checkpoint == 'apple-dyld':
        at_target = bool(user.get('observed') and int(user.get('pstate', '0xf'), 16) & 15 == 0 and
                         len(user.get('steps', [])) == 4 and dyld_bytes_match and
                         all(int(s['pstate'], 16) & 15 == 0 for s in user['steps']))
    if args.checkpoint == 'apple-main':
        at_target = bool(main_entry.get('first_instruction_completed') and dyld_bytes_match and main_bytes_match and
                         int(main_entry.get('checkpoint_pstate', '0xf'), 16) & 15 == 0)
    owners = lambda address: [e['module'] for e in plan['extents'] if e['va'] <= address < e['va']+e['size']]
    crypto_owner, amfi_owner = owners(values['_g_crypto_funcs']), owners(values['_amfi'])
    crypto_ready = values['_crypto_init'] == 1 and values['_prng_ready'] == 1 and crypto_owner == ['com.apple.kec.corecrypto']
    amfi_ready = amfi_owner == ['com.apple.driver.AppleMobileFileIntegrity']
    report = {'pass': bool(at_target and crypto_ready), 'checkpoint': args.checkpoint,
        'checkpoint_observed': at_target, 'kernel_sha256': digest, 'globals': values,
        'original_crypto_initialized': crypto_ready, 'crypto_table_owner': crypto_owner,
        'original_amfi_table_registered': amfi_ready, 'amfi_table_owner': amfi_owner,
        'software_aes_service_ready': all(values.get(n) == 1 for n in
            ['_native_aes_kat_status', '_native_aes_interface_status', '_native_aes_registered']),
        'actual_x0': observed['x0'], 'actual_pc': observed['pc'],
        'bounded_timeout_interrupted': observed['bounded_timeout_interrupted'],
        'syscall_events': observed.get('syscall_events', []),
        'guest_dyld_page_fault_control': observed.get('own_mapped_page_mutation'),
        'panic_observed': int(observed['pc'], 16) == names['_panic'],
        'panic_format': observed.get('argument_memory', {}).get('x0') if int(observed['pc'], 16) == names['_panic'] else None,
        'root_mounted': bool(args.checkpoint == 'vfs-root' and at_target and int(observed['x0'], 16) == 0),
        'observed_root_filesystem': filesystem,
        'original_apfs_root_mounted': filesystem == 'apfs',
        'own_static_el0_observed': bool(args.checkpoint == 'own-process' and at_target and int(observed['pstate'], 16) & 15 == 0),
        'ios_userspace_boot_demonstrated': False, 'marble_hardware_tested': False,
        'original_trust_cache_supplied': args.original_trust_cache,
        'qemu_vmm_present_declared': args.declare_qemu_vmm,
        'original_apple_dyld_entry': user,
        'original_dyld_observed_bytes_match': dyld_bytes_match,
        'original_apple_launchd_main': main_entry,
        'original_launchd_observed_bytes_match': main_bytes_match,
        'root_image_sha256': hashlib.sha256((payload / 'ram-root-fixture.img').read_bytes()).hexdigest(),
        'root_input': 'original_iPhone_20H392_restore_APFS' if args.iphone_restore_root else 'own_public_MockFS_fixture',
        'scope': ('Real original iPhone components and original restore APFS input; no full iOS UI demonstrated.'
                  if args.iphone_restore_root else
                  'Real original iPhone components on a native 4K XNU kernel; public RAM root fixture, no Apple userspace.')}
    if args.checkpoint == 'vfs-root':
        report['pass'] = report['pass'] and report['root_mounted'] and amfi_ready
        if args.iphone_restore_root:
            report['pass'] = report['pass'] and filesystem == 'apfs'
    if args.checkpoint == 'mach-load':
        report['mach_loader_return'] = int(observed['x0'], 16) if at_target else None
        report['pass'] = report['pass'] and report['mach_loader_return'] == 0
    if args.checkpoint == 'own-process':
        report['pass'] = report['pass'] and report['own_static_el0_observed'] and amfi_ready
    if args.checkpoint.startswith('apple-'):
        report['pass'] = report['pass'] and amfi_ready
    if args.corrupt_dyld_page:
        report['negative_control'] = 'Actual signed dyld code-page copy is changed only in QEMU RAM'
        report['signature_refusal_observed'] = bool(
            report['guest_dyld_page_fault_control'] and not user.get('observed') and
            values.get('_cs_validate_page_bad_hash', 0) > 0 and
            values.get('_cs_procs_killed', 0) > 0 and not observed['bounded_timeout_interrupted'])
        report['pass'] = report['signature_refusal_observed']
        live_page = observed.get('followed_relative_memory', {}).get('-0x1b0:0x1000', {}).get('bytes')
        report['executed_dyld_page_sha256'] = hashlib.sha256(bytes.fromhex(live_page)).hexdigest() if live_page and not live_page.startswith('E') else None
        report['executed_dyld_page_matches_original'] = report['executed_dyld_page_sha256'] == page_hash
    (out / 'result.json').write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps(report, indent=2))
    if not report['pass']:
        raise SystemExit('Original iPhone component checkpoint not established')


if __name__ == '__main__':
    main()
