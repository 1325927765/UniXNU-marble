"""Default off full process core files on the Marble development port.

Console crash diagnostics and the kern.coredump sysctl remain available.
"""
from pathlib import Path
from datetime import datetime
p=Path.home()/'unixnu-marble8796-build/xnu/bsd/kern/kern_core.c'
old=p.read_text()
anchor='#ifdef SECURE_KERNEL\n__XNU_PRIVATE_EXTERN int do_coredump = 0;'
assert old.count(anchor)==1
new=old.replace(anchor,'#if defined(SECURE_KERNEL) || defined(MARBLE)\n__XNU_PRIVATE_EXTERN int do_coredump = 0;',1)
backup=Path.home()/'unixnu-marble8796-build/trace-backups'/datetime.now().strftime('%Y%m%d-no-full-cores-%H%M%S')
backup.mkdir(parents=True,exist_ok=False)
(backup/p.name).write_text(old)
p.write_text(new)
print('patched',p,'backup',backup)
