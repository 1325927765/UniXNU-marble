"""Compile/link the isolated foundation kernel; this does not package or boot it."""
import hashlib
import json
from pathlib import Path
import re
import shutil
import struct
import subprocess

r = Path.home() / 'unixnu-marble8796-build'
p = r / 'qualification.json'
report = json.loads(p.read_text())
assert report['header_build_passed'] and report['legacy_iig_source_inputs_verified'] == 39
support = json.loads((r / 'support-report.json').read_text())
assert support['firehose_build_exit_code'] == 0
assert 'arm64' in support['firehose_architecture'] and 'arm64e' not in support['firehose_architecture']
path = r / 'xnu/makedefs/MakeInc.def'
text = path.read_text()
text, n = re.subn(r'^LDFLAGS_KERNEL_SDK\s*=.*$',
                   'LDFLAGS_KERNEL_SDK = -L$(FAKEROOT_DIR)/usr/local/lib/kernel', text, flags=re.M)
assert n == 1
text, n = re.subn(r'^INCFLAGS_SDK\s*=.*$',
                   'INCFLAGS_SDK = -I$(FAKEROOT_DIR)/usr/local/include/kernel', text, flags=re.M)
assert n == 1
if path.read_text() != text:
    path.write_text(text)
# Keep the real syntax checks; only select the installed Python interpreter.
checker = r / 'xnu/tools/lldbmacros/core/syntax_checker.py'
text = checker.read_text()
if text.startswith('#!/usr/bin/env python\n'):
    text = text.replace('#!/usr/bin/env python\n', '#!/usr/bin/env python3\n', 1)
if 'sys.path.pop(0)' not in text:
    assert text.count('import sys\n') == 1
    text = text.replace('import sys\n', 'import sys\n# Do not shadow stdlib collections with the adjacent LLDB module.\nsys.path.pop(0)\n', 1)
if checker.read_text() != text:
    checker.write_text(text)
identity = r / 'xnu/iokit/KernelConfigTables.cpp'
text = identity.read_text()
assert text.count('oneplus,marble') + text.count('xiaomi,marble') == 1
if 'oneplus,marble' in text:
    text = text.replace('oneplus,marble', 'xiaomi,marble')
assert text.count('qcom,kryo470') + text.count('marble,boot-cpu') == 1
text = text.replace('qcom,kryo470', 'marble,boot-cpu')
if identity.read_text() != text:
    identity.write_text(text)
cpu = r / 'xnu/iokit/Kernel/arm/MarbleCPU.cpp'
text = cpu.read_text().replace('withCStringNoCopy("Kryo 470")', 'withCStringNoCopy("marble boot CPU")')
if cpu.read_text() != text:
    cpu.write_text(text)
report['board_iokit_match'] = 'xiaomi,marble'
report['boot_cpu_iokit_match'] = 'marble,boot-cpu'
report['debug_syntax_checks_preserved'] = True
command = [x for x in report['kernel_build_command'] if not x.startswith('RC_NONARCH_CFLAGS=')]
command.append('RC_NONARCH_CFLAGS=-Wno-reserved-identifier -Wno-pre-c11-compat -Wno-pre-c23-compat')
report['kernel_build_command'] = command
report['support'] = support
report['kernel_linked'] = False
p.write_text(json.dumps(report, indent=2) + '\n')
with (r / 'kernel-supported.log').open('w') as log:
    result = subprocess.run(command, cwd=r / 'xnu', stdout=log, stderr=subprocess.STDOUT)
report['kernel_build_exit_code'] = result.returncode
candidate = r / 'fakeroot/System/Library/Kernels/kernel.development.marble'
if result.returncode == 0:
    assert candidate.is_file() and candidate.stat().st_size > 1000000
    unstripped = r / 'kernel.obj/DEVELOPMENT_ARM64_MARBLE/kernel.development.marble.unstripped'
    data = unstripped.read_bytes()
    assert struct.unpack_from('<4I', data) == (0xfeedfacf, 0x100000c, 0, 2)
    undefined = subprocess.check_output(['xcrun', 'nm', '-u', str(unstripped)], text=True).strip()
    assert not undefined, undefined
    artifacts = r / 'artifacts'
    artifacts.mkdir(exist_ok=True)
    shutil.copy2(unstripped, artifacts / 'marble8796-foundation.macho')
    with (artifacts / 'kernel-symbols.txt').open('w') as symbols:
        subprocess.run(['xcrun', 'nm', '-U', str(unstripped)], stdout=symbols, check=True)
    report.update(kernel_linked=True, kernel=str(candidate),
                  kernel_sha256=hashlib.sha256(candidate.read_bytes()).hexdigest(),
                  kernel_bytes=candidate.stat().st_size,
                  unstripped_sha256=hashlib.sha256(data).hexdigest(),
                  ordinary_arm64_mh_execute=True, undefined_symbols=[])
report['hardware_boot_tested'] = False
report['ios_userspace_booted'] = False
p.write_text(json.dumps(report, indent=2) + '\n')
print('KERNEL_BUILD_EXIT=' + str(result.returncode), flush=True)
raise SystemExit(result.returncode)
