"""Retry the real isolated header build after installing its OSS availability tool locally."""
import json
from pathlib import Path
import subprocess

root = Path.home() / 'unixnu-marble8796-build'
source = root / 'xnu'
report_path = root / 'qualification.json'
report = json.loads(report_path.read_text())
assert report['source_prepared'] and not report['kernel_linked']
script = source / 'bsd/sys/make_symbol_aliasing.sh'
original = 'AVAILABILITY_PL="${SDKROOT}/${DRIVERKITROOT}/usr/local/libexec/availability.pl"'
adapted = 'AVAILABILITY_PL="${FAKEROOT_DIR}/usr/local/libexec/availability.pl"'
text = script.read_text()
assert text.count(original) + text.count(adapted) == 1
script.write_text(text.replace(original, adapted))
tool = root / 'fakeroot/usr/local/libexec/availability.pl'
assert tool.is_file()
report['availability_versions_commit'] = subprocess.check_output(
    ['git', '-C', str(root / 'AvailabilityVersions'), 'rev-parse', 'HEAD'], text=True).strip()
report['availability_path_project_local'] = True
with (root / 'headers-build-retry.log').open('w') as log:
    result = subprocess.run(report['header_build_command'], cwd=source,
                            stdout=log, stderr=subprocess.STDOUT)
report['header_build_passed'] = result.returncode == 0
report['header_build_exit_code'] = result.returncode
report.pop('error', None)
if result.returncode:
    report['error'] = 'Actual header build failed; inspect headers-build-retry.log'
report_path.write_text(json.dumps(report, indent=2) + '\n')
print('HEADER_BUILD_EXIT=' + str(result.returncode), flush=True)
raise SystemExit(result.returncode)
