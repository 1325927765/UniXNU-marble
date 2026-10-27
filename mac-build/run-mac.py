#!/usr/bin/env python3
"""Prepare pinned sources, or build the source-only marble early XNU kernel.

Python 3.11+ is needed by upstream tomllib. --prepare-only does not need Xcode.
No phone, disk image, prelink or userdata operations are performed here.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import struct
import subprocess
import sys
from types import SimpleNamespace

PIN = '5fdbd5d08518bc2d5c196264c56a377dd80cf5ca'
SUBMODULES = {
    'drivers/ArmCpu': '1951cc8444b340d7d8879e9418220cf29eb711d7',
    'drivers/ArmDTPlatform': '0d544705c2e89725caabc0542bb96bc8febd8c70',
    'kits/NativePrelink': '2b6ffb50117eee820b98aca9bd51b5c7dfb2970e',
}
REFERENCES = {'xnu', 'libplatform', 'libdispatch', 'AvailabilityVersions', 'libpthread', 'corecrypto-2023'}


def prepare_patch_overlay(source, work, modules, ctx, virtual_timer_only=False, iphone16_compat=False, prelinked_crypto=False, signed_exec_policy=False, ufs_readonly_probe=False, hfs_mount_fixture=False):
    """Qualify the optional display hook, retaining pristine pinned sources."""
    name = 'offline-component-load-probes.patch'
    original = source / 'patches/xnu' / name
    overlay = work / 'overlays/xnu'
    shutil.copytree(original.parent, overlay, dirs_exist_ok=True)
    text = original.read_text()
    before = ('+\tint legacy_register = 0;\n'
              '+\tif (native_mobile_graphics_load_status == 0 &&\n'
              '+\t    PE_parse_boot_argn("offline-legacy-register", &legacy_register, sizeof(legacy_register)) && legacy_register) {\n'
              '+\t\textern void native_legacy_display_probe(void);\n'
              '+\t\tnative_legacy_display_probe();\n+\t}\n')
    after = ('+#if defined(XNU_NATIVE_LEGACY_DISPLAY) && XNU_NATIVE_LEGACY_DISPLAY\n'
             + before + '+#endif\n')
    if text.count(before) != 1 or text.count('@@ -478,5 +478,88 @@') != 1:
        raise SystemExit('Pinned optional display hook patch differs')
    text = text.replace(before, after).replace('@@ -478,5 +478,88 @@', '@@ -478,5 +478,90 @@')
    text = text.replace('@@ -698,6 +774,27 @@', '@@ -698,6 +776,27 @@')
    corrected = overlay / name
    corrected.write_text(text)
    cached = ctx.tree / '.cache/xnu-work'
    if (cached / '.git').is_dir():
        def applied(patch):
            return subprocess.run(['git', '-C', str(cached), 'apply', '--reverse', '--check', str(patch)],
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0
        if not applied(corrected) and applied(original):
            run(['git', '-C', cached, 'apply', '--reverse', original])
    # This additional patch is scoped to the explicit marble build variant.
    board_name = 'marble-virtual-timer-only.patch'
    board_patch = Path(__file__).resolve().parent / 'patches' / board_name
    board_target = overlay / board_name
    if virtual_timer_only:
        shutil.copyfile(board_patch, board_target)
    else:
        if (cached / '.git').is_dir() and applied(board_patch):
            run(['git', '-C', cached, 'apply', '--reverse', board_patch])
        board_target.unlink(missing_ok=True)
    rpc_name = 'marble-iphone16-rpc.patch'
    rpc_patch = Path(__file__).resolve().parent / 'patches' / rpc_name
    if iphone16_compat:
        shutil.copyfile(rpc_patch, overlay / rpc_name)
    else:
        if (cached / '.git').is_dir() and applied(rpc_patch):
            run(['git', '-C', cached, 'apply', '--reverse', rpc_patch])
        (overlay / rpc_name).unlink(missing_ok=True)
    boot_name = 'zzzz-marble-iphone16-bootcrypto.patch'
    boot_patch = Path(__file__).resolve().parent / 'patches' / boot_name
    # The overlay adjusts contexts also touched by the pinned prelink patch.
    # Restore our delta before the builder checks that pinned patch, then apply
    # this explicitly named overlay last in the sorted patch sequence.
    if (cached / '.git').is_dir() and applied(boot_patch):
        run(['git', '-C', cached, 'apply', '--reverse', boot_patch])
    (overlay / boot_name).unlink(missing_ok=True)
    # The builder checks kits/NativePrelink/patches after patches/xnu. Keep our
    # dependent delta at the end of that second sequence, in an isolated copy.
    kit_overlay = work / 'overlays/NativePrelink'
    shutil.copytree(source / 'kits/NativePrelink', kit_overlay, dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns('.git', '__pycache__'))
    (kit_overlay / 'patches' / boot_name).unlink(missing_ok=True)
    prng_name = 'marble-iphone16-entropy-abi.patch'
    prng_patch = Path(__file__).resolve().parent / 'patches' / prng_name
    if (cached / '.git').is_dir() and applied(prng_patch):
        run(['git', '-C', cached, 'apply', '--reverse', prng_patch])
    if prelinked_crypto:
        shutil.copyfile(prng_patch, overlay / prng_name)
    else:
        (overlay / prng_name).unlink(missing_ok=True)
    policy_name = 'marble-iphone16-signed-exec.patch'
    policy_patch = Path(__file__).resolve().parent / 'patches' / policy_name
    if (cached / '.git').is_dir() and applied(policy_patch):
        run(['git', '-C', cached, 'apply', '--reverse', policy_patch])
    if signed_exec_policy:
        shutil.copyfile(policy_patch, overlay / policy_name)
    else:
        (overlay / policy_name).unlink(missing_ok=True)
    modules[('kit', 'NativePrelink')].path = kit_overlay
    hfs_name='zzzzz-marble-hfs-mount-fixture.patch'
    hfs_patch=Path(__file__).resolve().parent/'patches'/hfs_name
    if (cached/'.git').is_dir() and applied(hfs_patch):
        run(['git','-C',cached,'apply','--reverse',hfs_patch])
    if hfs_mount_fixture:
        shutil.copyfile(hfs_patch,overlay/hfs_name)
    else:
        (overlay/hfs_name).unlink(missing_ok=True)
    probe_name = 'zzzz-marble-ufs-readonly-probe.patch'
    probe_patch = Path(__file__).resolve().parent / 'patches' / probe_name
    if (cached / '.git').is_dir() and applied(probe_patch):
        run(['git', '-C', cached, 'apply', '--reverse', probe_patch])
    if ufs_readonly_probe:
        shutil.copyfile(probe_patch, overlay / probe_name)
    else:
        (overlay / probe_name).unlink(missing_ok=True)
    modules[('kit', 'NativePrelink')].origin = 'pinned NativePrelink plus explicit marble bootstrap overlay'
    modules[('patch', 'xnu')].path = overlay
    modules[('patch', 'xnu')].origin = 'local pinned-patch overlay (optional display hook guard)'
    return {'path': name, 'original_sha256': hashlib.sha256(original.read_bytes()).hexdigest(),
            'overlay_sha256': hashlib.sha256(corrected.read_bytes()).hexdigest(),
            'change': 'Compile optional legacy display call only when its actual driver is enabled',
            'iphone16_rpc': ({'path': rpc_name, 'sha256': hashlib.sha256(rpc_patch.read_bytes()).hexdigest(),
                'scope': 'Restore Apple XNU 8796 ordinary ARM64 request/reply parser entry'} if iphone16_compat else None),
            'iphone16_entropy_abi': ({'path': prng_name, 'sha256': hashlib.sha256(prng_patch.read_bytes()).hexdigest(),
                'scope': 'Use Apple XNU 8796 entropy ABI for original corecrypto 12; retain normal OSKext start, native health tests and POST'} if prelinked_crypto else None),
            'iphone16_signed_exec_policy': ({'path': policy_name, 'sha256': hashlib.sha256(policy_patch.read_bytes()).hexdigest(),
                'scope': 'Apply the explicitly enabled global signed-exec policy to the actual process/map; preserve original signature results'} if signed_exec_policy else None),
            'marble_virtual_timer_only': ({'path': board_name, 'sha256': hashlib.sha256(board_patch.read_bytes()).hexdigest(),
                'scope': 'Explicit marble-only overlay; leave CNTV enabled and omit inaccessible CNTP_CTL_EL0 write'} if virtual_timer_only else None)}


def run(command, **kwargs):
    print('+', ' '.join(map(str, command)), flush=True)
    return subprocess.run(list(map(str, command)), check=True, **kwargs)


def revision(path):
    return subprocess.check_output(['git', '-C', str(path), 'rev-parse', 'HEAD'], text=True).strip()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--work', type=Path, default=Path.home() / 'unixnu-marble-build')
    parser.add_argument('--prepare-only', action='store_true')
    parser.add_argument('--virtual-timer-only', action='store_true', help='Apply marble-only source fix for observed CNTP_CTL_EL0 UNDEF')
    parser.add_argument('--ufs-readonly-probe', action='store_true', help='Explicit marble diagnostics; boot argument selects register, SCSI or BSD read tests')
    parser.add_argument('--hfs-mount-fixture', type=Path, help='QEMU HFSX mount experiment; path to the separately compiled Apple HFS archive')
    parser.add_argument('--ram-root-fixture', action='store_true', help='QEMU-only public MockFS/md0 root qualification; contains no Apple userspace')
    parser.add_argument('--iphone16-compat', action='store_true', help='Restore the real legacy IORPCMessageFromMach implementation for iPhone iOS 16')
    parser.add_argument('--prelinked-crypto', action='store_true', help='Require original prelinked crypto initialization; raw output cannot boot alone')
    parser.add_argument('--trust-cache-runtime', action='store_true', help='Initialize the genuine XNU trust cache runtime before original AMFI queries it')
    parser.add_argument('--native-signature-hash-cache', action='store_true', help='Authenticate original 16K signed blocks before deriving native 4K page digests')
    parser.add_argument('--native-pan', action='store_true', help='Use the existing ARMv8.1+ PAN support for actual PAN-capable QEMU/marble CPUs')
    parser.add_argument('--enforce-signed-code', action='store_true', help='Require genuine code signing enforcement for every process')
    parser.add_argument('--iphone16-aes-bindings', type=Path, help='Measured original iPhone16 AES ABI bindings; enable the real software-only AES subclass')
    parser.add_argument('--jobs', type=int, default=4)
    parser.add_argument('--artifact-set', help='Separate named artifact/report directory; keeps earlier kernel exports intact')
    args = parser.parse_args()
    if args.iphone16_aes_bindings:
        args.iphone16_aes_bindings = args.iphone16_aes_bindings.expanduser().resolve()
        measured = json.loads(args.iphone16_aes_bindings.read_text())
        if (not args.prelinked_crypto or not args.native_pan or not args.enforce_signed_code or
                not measured['live_instance_sizes_qualified'] or measured['other_device_recorded_bindings_used'] or
                measured['original_sha256'] != '2ec297bac95bcba01046fd0148e97e7e5885c05a6c18827f39f534ba375c1221'):
            parser.error('NativeAES requires measured iPhone16 bindings and the explicit native/enforced profile')
        SUBMODULES['drivers/NativeAES'] = 'a34964b8c2fec2e83c8e4f68fb7d6fb7e4b2227b'
    if args.artifact_set and not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,63}', args.artifact_set):
        parser.error('artifact-set must be a short lowercase name')
    if sys.version_info < (3, 11):
        parser.error('Use Python 3.11+ (Homebrew python@3.13 is suitable)')
    if args.jobs < 1:
        parser.error('--jobs must be positive')
    home = Path(__file__).resolve().parent
    work = args.work.expanduser().resolve()
    work.mkdir(parents=True, exist_ok=True)
    source = work / 'sources/UniXNU'
    if not (source / '.git').exists():
        source.mkdir(parents=True, exist_ok=True)
        run(['git', '-C', source, 'init', '-q'])
        run(['git', '-C', source, 'remote', 'add', 'origin', 'https://github.com/UniXNU/UniXNU.git'])
        run(['git', '-C', source, 'fetch', '--depth', '1', 'origin', PIN])
        run(['git', '-C', source, 'checkout', '--detach', 'FETCH_HEAD'])
    if revision(source) != PIN:
        raise SystemExit('Existing UniXNU source revision differs; select a fresh --work')
    dirty = subprocess.check_output(['git', '-C', str(source), 'status', '--porcelain', '--untracked-files=no'], text=True)
    dirty_entries = {line for line in dirty.splitlines() if line.strip()}
    allowed_diagnostic_change = {' M drivers/NativeAES', ' m drivers/NativeAES'} if (
        (args.iphone16_aes_bindings and measured.get('diagnostic_stage_markers')) or
        not args.iphone16_aes_bindings) else set()
    # NativeAES is not selected without explicit measured bindings. Preserve an
    # earlier diagnostic checkout without incorporating it into this build.
    if dirty_entries - allowed_diagnostic_change:
        raise SystemExit('Pinned base source has tracked changes; refusing to overwrite')
    run(['git', '-C', source, 'submodule', 'update', '--init', '--depth', '1', '--', *SUBMODULES])
    for name, pin in SUBMODULES.items():
        if revision(source / name) != pin:
            raise SystemExit(f'Unexpected revision: {name}')
    sys.path.insert(0, str(source / 'scripts'))
    from unixnu import config, feeds, kernel, tree
    context_args = SimpleNamespace(out=str(work / 'out'), device=str(home / 'device'), jobs=args.jobs,
                                   local_module=[], local=None,
                                   **{'local_' + name: None for name in config.LOCAL_KINDS})
    ctx = config.Context(context_args)
    ctx.work.mkdir(parents=True, exist_ok=True)
    ctx.logs.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(home / 'device/configs/marble_early_defconfig', ctx.config_path)
    ctx.config = config.parse_config(ctx.config_path.read_text())
    if args.ram_root_fixture:
        with ctx.config_path.open('a') as stream:
            stream.write('\nCONFIG_XNU_SOURCE_MOCKFS=y\n')
        ctx.config = config.parse_config(ctx.config_path.read_text())
        ctx.board['kernel']['archives'].append('build-mockfs-fixture.py')
    if args.prelinked_crypto:
        if not args.iphone16_compat:
            parser.error('--prelinked-crypto currently requires the explicit iPhone16 experiment')
        with ctx.config_path.open('a') as stream:
            stream.write('\nCONFIG_XNU_CRYPTO_BOOTSTRAP="prelinked"\n')
        ctx.config = config.parse_config(ctx.config_path.read_text())
    if args.trust_cache_runtime:
        if not args.prelinked_crypto:
            parser.error('--trust-cache-runtime requires the explicit original-provider experiment')
        with ctx.config_path.open('a') as stream:
            stream.write('\nCONFIG_XNU_TRUST_CACHE_RUNTIME=y\n')
        ctx.config = config.parse_config(ctx.config_path.read_text())
    if args.native_signature_hash_cache:
        if not args.trust_cache_runtime:
            parser.error('--native-signature-hash-cache requires the genuine trust-cache runtime')
        with ctx.config_path.open('a') as stream:
            stream.write('\nCONFIG_XNU_NATIVE_CS_HASH_CACHE=y\n')
        ctx.config = config.parse_config(ctx.config_path.read_text())
    if args.native_pan:
        with ctx.config_path.open('a') as stream:
            stream.write('\nCONFIG_XNU_NATIVE_PAN=y\n')
        ctx.config = config.parse_config(ctx.config_path.read_text())
    if args.enforce_signed_code:
        if not args.trust_cache_runtime:
            parser.error('--enforce-signed-code requires the original-provider/trust-cache experiment')
        build_script = (source / 'scripts/build-xnu-4k-baseline.sh').read_text()
        defaults = re.findall(r'^EXTRA_CFLAGS=\$\{XNU_EXTRA_CFLAGS:-(.+)\}$', build_script, re.M)
        if len(defaults) != 1 or 'CONFIG_ENFORCE_SIGNED_CODE' in defaults[0]:
            raise ValueError('Pinned compiler flags differ')
        flags = defaults[0] + ' -DCONFIG_ENFORCE_SIGNED_CODE=1'
        with ctx.config_path.open('a') as stream:
            stream.write('\nCONFIG_XNU_EXTRA_CFLAGS=' + json.dumps(flags) + '\n')
        ctx.config = config.parse_config(ctx.config_path.read_text())
    if args.iphone16_aes_bindings:
        with ctx.config_path.open('a') as stream:
            stream.write('\nCONFIG_XNU_NATIVE_AES=y\nCONFIG_XNU_IPHONE16_AES_BINDINGS=' +
                         json.dumps(str(args.iphone16_aes_bindings)) + '\n')
        ctx.config = config.parse_config(ctx.config_path.read_text())
        ctx.board['kernel']['archives'].append('build-marble-arm-driver.py NativeAES')
    selected = {('driver', 'ArmCpu'), ('driver', 'ArmDTPlatform'), ('kit', 'NativePrelink'),
                ('patch', 'xnu'), ('patch', 'libpthread'), ('package', 'main')}
    selected |= {('refer', name) for name in REFERENCES}
    if args.iphone16_aes_bindings:
        selected.add(('driver', 'NativeAES'))
    resolved = feeds.resolve(ctx)
    modules = {key: value for key, value in resolved.items() if key in selected}
    if selected != modules.keys():
        raise SystemExit(f'Missing required modules: {selected - modules.keys()}')
    commits = feeds.fetch(ctx, modules, only=REFERENCES)
    feeds.lock_write(ctx, commits)
    local_patch = prepare_patch_overlay(source, work, modules, ctx,
        virtual_timer_only=args.virtual_timer_only, iphone16_compat=args.iphone16_compat,
        prelinked_crypto=args.prelinked_crypto, signed_exec_policy=args.enforce_signed_code,
        ufs_readonly_probe=args.ufs_readonly_probe, hfs_mount_fixture=bool(args.hfs_mount_fixture))
    tree.assemble(ctx, modules)
    report = {'base_commit': PIN, 'submodules': SUBMODULES, 'references': commits,
              'local_patch_overlay': local_patch,
              'source_prepared': True, 'kernel_built': False, 'hardware_boot_observed': False,
              'profile': 'source-only; single-core intended; no storage/userspace/prelink'}
    report['ram_root_fixture'] = args.ram_root_fixture
    report['iphone16_rpc_compat_requested'] = args.iphone16_compat
    report['crypto_bootstrap'] = 'prelinked' if args.prelinked_crypto else 'source'
    report['trust_cache_runtime_requested'] = args.trust_cache_runtime
    report['native_signature_hash_cache_requested'] = args.native_signature_hash_cache
    report['native_pan_requested'] = args.native_pan
    report['enforce_signed_code_requested'] = args.enforce_signed_code
    report['iphone16_software_aes_bindings'] = (str(args.iphone16_aes_bindings) if args.iphone16_aes_bindings else None)
    if args.ram_root_fixture:
        report['profile'] = 'QEMU-only public XNU md0/MockFS fixture; no iOS userspace, APFS or UFS'
    artifact_dir = work / 'artifacts'
    if args.artifact_set: artifact_dir /= args.artifact_set
    artifact_dir.mkdir(parents=True, exist_ok=True)
    report_path = artifact_dir / 'build-report.json' if args.artifact_set else work / 'build-report.json'
    report['config_sha256'] = hashlib.sha256(ctx.config_path.read_bytes()).hexdigest()
    report['dt_panic_region_required'] = ctx.config.get('XNU_DT_PANIC_REGION') is True
    report['marble_virtual_timer_only_patch_requested'] = args.virtual_timer_only
    report['marble_ufs_readonly_probe_requested'] = args.ufs_readonly_probe
    report['hfs_mount_fixture_requested'] = bool(args.hfs_mount_fixture)
    if args.hfs_mount_fixture:
        archive=args.hfs_mount_fixture.expanduser().resolve()
        if not args.ufs_readonly_probe or not archive.is_file():
            raise SystemExit('HFS fixture needs the explicit probe integration and an existing HFS archive')
        os.environ['XNU_EXTRA_LD_ARCHIVES']='-Wl,-force_load,'+str(archive)
        report['hfs_archive_sha256']=hashlib.sha256(archive.read_bytes()).hexdigest()
        report['profile']='QEMU HFSX/md0 mount experiment; no iOS userspace or phone filesystem writes'
    report_path.write_text(json.dumps(report, indent=2) + '\n')
    if args.prepare_only:
        print('Source preparation complete. XNU has not been compiled.')
        return
    if platform.system() != 'Darwin':
        raise SystemExit('Actual XNU compilation requires macOS and full Xcode')
    os.environ['PATH'] = '/opt/homebrew/bin:/usr/local/bin:' + os.environ.get('PATH', '')
    sdk = subprocess.check_output(['xcrun', '--sdk', 'iphoneos', '--show-sdk-path'], text=True).strip()
    run(['xcodebuild', '-version'])
    report['sdk'] = sdk
    # The full-ROM CLI also prelinks. This dedicated source-only experiment invokes
    # only its public-source kernel builder, retaining example=true on both boards.
    kernel.build(ctx, modules)
    candidate = ctx.tree / 'build/xnu/ios-obj/DEVELOPMENT_ARM64_BCM2837/mach.development.bcm2837.unstripped.noctf'
    data = candidate.read_bytes()
    if len(data) < 32 or struct.unpack_from('<4I', data) != (0xfeedfacf, 0x100000c, 0, 2):
        raise SystemExit('Build output is not ordinary ARM64 MH_EXECUTE')
    output = artifact_dir / 'marble-early-source-kernel.macho'
    output.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(candidate, output)
    report.update(kernel_built=True, kernel=str(output), kernel_sha256=hashlib.sha256(data).hexdigest(),
                  kernel_bytes=len(data), hardware_boot_observed=False)
    run([sys.executable, ctx.tree / 'scripts/audit-xnu-kernel.py', output])
    shutil.copyfile(ctx.tree / 'build/xnu/kernel-audit.json', output.parent / 'kernel-audit.json')
    with (output.parent / 'kernel-symbols.txt').open('w') as symbols:
        run(['xcrun', 'nm', '-U', output], stdout=symbols)
    report_path.write_text(json.dumps(report, indent=2) + '\n')
    print(f'Source kernel built: {output}. Device handoff remains untested.')


if __name__ == '__main__':
    main()
