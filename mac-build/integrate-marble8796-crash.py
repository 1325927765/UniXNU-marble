"""Apply software-only process crash registers/reasons, excluding KeyStore changes."""
from pathlib import Path
import subprocess
import zipfile

r = Path.home()/'unixnu-marble8796-build'
stage = r/'crash-stage'
with zipfile.ZipFile(Path.home()/'unixnu-marble-kit/crash-diagnostics.zip') as z:
    z.extractall(stage)
for p in sorted(stage.glob('*.patch')):
    subprocess.run(['git','apply','--check',str(p)],cwd=r/'xnu',check=True)
    subprocess.run(['git','apply',str(p)],cwd=r/'xnu',check=True)
p = r/'xnu/osfmk/kern/exception.c'
text = p.read_text()
anchor = ('\tthread_t thread = current_thread();\n\ttask_t task = current_task();\n'
          '\tarm_saved_state_t *ss = find_user_regs(thread);')
assert text.count(anchor) == 1
text = text.replace(anchor,
    '\tint enabled = 0;\n'
    '\tif (!PE_parse_boot_argn("marble_crash_log", &enabled, sizeof(enabled)) || !enabled) return;\n'
    + anchor)
p.write_text(text)
print('Process crash register logs gated by marble_crash_log=1; exit reasons logged on crash')
