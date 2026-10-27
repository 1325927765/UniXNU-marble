"""Add bounded timer and startup checkpoints to the MARBLE diagnostic kernel."""
from datetime import datetime
from pathlib import Path
import json

root=Path.home()/'unixnu-marble8796-build/xnu'
changes={}
path=root/'osfmk/arm/rtclock.c'
text=path.read_text()
anchor='\tcdp->cpu_stat.timer_cnt++;'
if text.count(anchor)!=1 or 'MARBLE TIMER: count=' in text:
    raise SystemExit('unexpected timer source; no changes')
text=text.replace('#include <mach/mach_types.h>', '#include <mach/mach_types.h>\n#include <pexpert/pexpert.h>',1)
text=text.replace(anchor,anchor+'''
#if defined(MARBLE)
    if (cdp->cpu_stat.timer_cnt <= 3 || cdp->cpu_stat.timer_cnt == 100) {
        kprintf("MARBLE TIMER: count=%llu\\n", (unsigned long long)cdp->cpu_stat.timer_cnt);
    }
#endif
''',1)
changes[path]=text
for relative,anchor,message,logger in [
    ('bsd/kern/bsd_init.c','bsd_init(void)\n{','bsd_init reached','printf'),
    ('osfmk/kern/startup.c','kernel_bootstrap(void)\n{','kernel_bootstrap reached','printf'),
    ('iokit/bsddev/IOKitBSDInit.cpp','IOFindBSDRoot( char * rootName, unsigned int rootNameSize,\n    dev_t * root, u_int32_t * oflags )\n{','IOFindBSDRoot reached','IOLog')]:
    path=root/relative
    text=path.read_text()
    if text.count(anchor)!=1 or 'MARBLE BOOT: '+message in text:
        raise SystemExit(f'unexpected checkpoint source {relative}; no changes')
    changes[path]=text.replace(anchor,anchor+f'\n#if defined(MARBLE)\n    {logger}("MARBLE BOOT: {message}\\n");\n#endif\n',1)
backup=Path.home()/'unixnu-marble8796-build/trace-backups'/datetime.now().strftime('%Y%m%d-hardware-startup-%H%M%S')
backup.mkdir(parents=True,exist_ok=False)
for path,new in changes.items():
    dest=backup/path.relative_to(root)
    dest.parent.mkdir(parents=True,exist_ok=True)
    dest.write_text(path.read_text())
for path,new in changes.items():
    path.write_text(new)
print(json.dumps(dict(backup=str(backup),patched=[str(p) for p in changes]),indent=2))
