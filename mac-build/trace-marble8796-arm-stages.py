"""Mark the cold arm_init path around platform and timebase setup."""
from datetime import datetime
from pathlib import Path

root=Path.home()/'unixnu-marble8796-build/xnu'
path=root/'osfmk/arm/arm_init.c'
old=path.read_text()
if 'MARBLE ARM:' in old:
    raise SystemExit('ARM trace already present; no change')
start=old.index('arm_init(\n')
finish=old.index('machine_startup(args);',start)+len('machine_startup(args);')
body=old[start:finish]
calls=['cpu_machine_idle_init(TRUE);','PE_init_platform(TRUE, &BootCpuData);',
       'ml_map_cpu_pio();','cpu_timebase_init(TRUE);','kptimer_curcpu_up();',
       'PE_init_cpu();','fiq_context_init(TRUE);','machine_startup(args);']
for n,call in enumerate(calls,1):
    if body.count(call)!=1:
        raise SystemExit(f'unexpected cold-boot checkpoint {call}; no change')
    body=body.replace(call,f'kprintf("MARBLE ARM: {n} before {call[:-1]}\\n");\n\t'+call+f'\n\tkprintf("MARBLE ARM: {n} after\\n");',1)
backup=Path.home()/'unixnu-marble8796-build/trace-backups'/datetime.now().strftime('%Y%m%d-arm-stages-%H%M%S')
backup.mkdir(parents=True,exist_ok=False)
(backup/'arm_init.c').write_text(old)
path.write_text(old[:start]+body+old[finish:])
print(f'patched={path}\nbackup={backup / "arm_init.c"}')
