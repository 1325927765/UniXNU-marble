"""Enable the upstream bindfs implementation required by iOS mount phase 1."""
from pathlib import Path
from datetime import datetime
p=Path.home()/'unixnu-marble8796-build/xnu/config/MASTER.arm64.marble'
old=p.read_text()
line=next(x for x in old.splitlines() if 'FILESYS_BASE = ' in x)
assert ' bindfs ' not in line and ' nullfs ' in line
backup=Path.home()/'unixnu-marble8796-build/trace-backups'/datetime.now().strftime('%Y%m%d-bindfs-%H%M%S')
backup.mkdir(parents=True,exist_ok=False)
(backup/p.name).write_text(old)
p.write_text(old.replace(line,line.replace(' nullfs ',' nullfs bindfs '),1))
print('Enabled upstream bindfs:',p,'backup:',backup)
