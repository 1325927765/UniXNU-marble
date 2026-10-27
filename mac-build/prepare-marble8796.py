"""Prepare isolated XNU 8796 sources and run an actual header-build qualification.

No system installations, phone commands, or modifications to the working 10063 tree.
"""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import zipfile

root = Path.home() / 'unixnu-marble8796-build'
source = root / 'xnu'
kit = Path.home() / 'unixnu-marble-kit/marble8796-foundation.zip'
report_path = root / 'qualification.json'
report = dict(xnu_commit='1b191cb58250d0705d8a51287127505aa4bc0789',
              tag='xnu-8796.141.3', source_prepared=False,
              header_build_passed=False, kernel_linked=False,
              hardware_boot_tested=False, ios_userspace_booted=False)


def run(args, **kwargs):
    print('+', ' '.join(map(str, args)), flush=True)
    return subprocess.run(list(map(str, args)), check=True, **kwargs)


def save():
    report_path.write_text(json.dumps(report, indent=2) + '\n')


try:
    actual = subprocess.check_output(['git', '-C', str(source), 'rev-parse', 'HEAD'], text=True).strip()
    assert actual == report['xnu_commit']
    assert subprocess.check_output(['git', '-C', str(source), 'rev-parse', report['tag']], text=True).strip() == 'f625db25f47631424dc62ac1c3414b6e530f7e8a'
    destination = root / 'foundation'
    assert not destination.exists(), 'Fresh qualification directory required'
    destination.mkdir()
    with zipfile.ZipFile(kit) as z:
        assert all('..' not in Path(n).parts and not Path(n).is_absolute() for n in z.namelist())
        z.extractall(destination)
    manifest = json.loads((destination / 'foundation-manifest.json').read_text())
    report['foundation_manifest'] = manifest
    patches = destination / 'patches'
    for entry in manifest['patches']:
        assert hashlib.sha256((patches / entry['file']).read_bytes()).hexdigest() == entry['adapted_sha256']
    env = os.environ.copy()
    env.update(MACHINE_CONFIG='MARBLE', MACOS_VERSION='13.5')
    env['PATH'] = '/opt/homebrew/bin:/usr/local/bin:' + env['PATH']
    with (root / 'staging.log').open('w') as log:
        for script in sorted(patches.glob('*.sh')):
            run(['bash', script], cwd=source, env=env, stdout=log, stderr=subprocess.STDOUT)
    report['applied_patches'] = []
    with (root / 'patching.log').open('w') as log:
        for patch in sorted(patches.glob('*.patch')):
            run(['git', 'apply', '--check', patch], cwd=source, stdout=log, stderr=subprocess.STDOUT)
            run(['git', 'apply', patch], cwd=source, stdout=log, stderr=subprocess.STDOUT)
            report['applied_patches'].append(patch.name)
            save()
    assert not (source / 'bsd/dev/marble_ufs.c').exists()
    assert '#define GICR_PE_SIZE              0x40000' in (source / 'pexpert/pexpert/arm64/MARBLE.h').read_text()
    report['source_prepared'] = True
    report['xcode'] = subprocess.check_output(['xcodebuild', '-version'], text=True).strip()
    report['sdk'] = subprocess.check_output(['xcrun', '--sdk', 'macosx', '--show-sdk-path'], text=True).strip()
    save()
    command = ['make', 'installhdrs', '-j4', 'SDKROOT=macosx',
               'TARGET_CONFIGS=DEVELOPMENT ARM64 MARBLE', 'ARCH_CONFIGS=ARM64',
               'SRCROOT=' + str(source), 'OBJROOT=' + str(root / 'headers.obj'),
               'SYMROOT=' + str(root / 'headers.sym'), 'DSTROOT=' + str(root / 'fakeroot'),
               'FAKEROOT_DIR=' + str(root / 'fakeroot'), 'BUILD_WERROR=0',
               'RC_DARWIN_KERNEL_VERSION=22.6.0', 'KERNEL_BUILDS_IN_PARALLEL=1']
    report['header_build_command'] = command
    save()
    with (root / 'headers-build.log').open('w') as log:
        run(command, cwd=source, env=env, stdout=log, stderr=subprocess.STDOUT)
    report['header_build_passed'] = True
except Exception as exc:
    report['error'] = str(exc)
    raise
finally:
    save()
