"""Build the matching open-source kernel logging archive in the isolated fakeroot."""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess

r = Path.home() / 'unixnu-marble8796-build'
report = {}
env = os.environ.copy()
env['PATH'] = '/opt/homebrew/bin:/usr/local/bin:' + env['PATH']
for project, tag in [('libplatform', 'libplatform-292.120.1.0.1'),
                     ('libdispatch', 'libdispatch-1415.140.2')]:
    path = r / project
    if not path.exists():
        subprocess.run(['git', 'clone', '--depth', '1', '--branch', tag,
                        'https://github.com/apple-oss-distributions/' + project, str(path)], check=True)
    assert subprocess.check_output(['git', '-C', str(path), 'describe', '--tags', '--exact-match'], text=True).strip() == tag
    report[project] = dict(tag=tag, commit=subprocess.check_output(['git', '-C', str(path), 'rev-parse', 'HEAD'], text=True).strip())
for directory in ('include', 'private'):
    shutil.copytree(r / 'libplatform' / directory, r / 'fakeroot/usr/local/include', dirs_exist_ok=True)
config = r / 'libdispatch/xcodeconfig/libfirehose_kernel.xcconfig'
text = config.read_text().replace('$(SDKROOT)/System/Library/Frameworks/Kernel.framework/PrivateHeaders',
                                  '$(FAKEROOT_DIR)/System/Library/Frameworks/Kernel.framework/PrivateHeaders')
text = text.replace('$(SDKROOT)/usr/local/include', '$(FAKEROOT_DIR)/usr/local/include')
config.write_text(text)
command = ['xcodebuild', 'install', '-target', 'libfirehose_kernel', '-sdk', 'macosx',
           'ARCHS=arm64', 'VALID_ARCHS=arm64', 'ONLY_ACTIVE_ARCH=NO',
           'OBJROOT=' + str(r / 'firehose.obj'), 'SYMROOT=' + str(r / 'firehose.sym'),
           'DSTROOT=' + str(r / 'fakeroot'), 'FAKEROOT_DIR=' + str(r / 'fakeroot'),
           'CODE_SIGNING_ALLOWED=NO', 'GCC_TREAT_WARNINGS_AS_ERRORS=NO']
with (r / 'support-build.log').open('w') as log:
    result = subprocess.run(command, cwd=r / 'libdispatch', env=env, stdout=log, stderr=subprocess.STDOUT)
report['firehose_build_exit_code'] = result.returncode
if result.returncode == 0:
    archive = r / 'fakeroot/usr/local/lib/kernel/libfirehose_kernel.a'
    shutil.copyfile(archive.with_name('liblibfirehose_kernel.a'), archive)
    report['firehose_sha256'] = hashlib.sha256(archive.read_bytes()).hexdigest()
    report['firehose_architecture'] = subprocess.check_output(['xcrun', 'lipo', '-info', str(archive)], text=True).strip()
(r / 'support-report.json').write_text(json.dumps(report, indent=2) + '\n')
print('SUPPORT_BUILD_EXIT=' + str(result.returncode))
raise SystemExit(result.returncode)
