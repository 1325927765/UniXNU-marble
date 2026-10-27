"""Build a guarded setup-preference delta from a verified private phone snapshot.

Mac-only. Edits an APFS clone, never the input snapshot or a phone.
Run with sudo for preserving the mobile preference ownership.
"""
import argparse
import hashlib
import os
from pathlib import Path
import plistlib
import subprocess
import sys

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--compressed', type=Path, required=True)
p.add_argument('--base-sha256', required=True)
p.add_argument('--folder', type=Path, required=True)
a = p.parse_args()
assert os.geteuid() == 0
assert not a.folder.exists()
a.folder.mkdir(parents=True, mode=0o700)
base, work, mount = (a.folder/name for name in ('base.cdr','work.cdr','mounted'))
mount.mkdir()
def run(*cmd, **kw): return subprocess.run([str(x) for x in cmd], check=True, **kw)
print('DECOMPRESS snapshot', flush=True)
run('/opt/homebrew/bin/zstd','-d','-q',a.compressed,'-o',base)
print('VERIFY full snapshot SHA256', flush=True)
h = hashlib.sha256()
with base.open('rb') as f:
    while chunk := f.read(8*1024**2): h.update(chunk)
assert h.hexdigest() == a.base_sha256 and base.stat().st_size == 16*1024**3
print('BASE SHA256 PASS; clone offline work image', flush=True)
run('/bin/cp','-c',base,work)
result = subprocess.check_output(['hdiutil','attach','-readwrite','-nobrowse','-noverify',
    '-mountpoint',str(mount),'-plist',str(work)])
entities = plistlib.loads(result)['system-entities']
device = entities[0]['dev-entry']; assert device.startswith('/dev/disk')
try:
    assert any(e.get('mount-point') and Path(e['mount-point']).resolve() == mount.resolve()
               for e in entities)
    script = Path(__file__).with_name('prepare-marble-ios16-setup-skip.py')
    print('DRY-RUN preference edit', flush=True)
    run(sys.executable,script,'--root',mount)
    print('MERGE preference edit into clone', flush=True)
    run(sys.executable,script,'--root',mount,'--backup-dir',a.folder/'preferences-backup','--apply')
finally:
    run('hdiutil','detach',device)
print('CREATE bounded forward/rollback blocks', flush=True)
run(sys.executable,Path(__file__).with_name('make-marble-guarded-delta.py'),base,work,a.folder/'delta')
run('tar','-czf',a.folder/'setup-skip-delta.tar.gz','-C',a.folder,'delta','preferences-backup/manifest.json')
print('SETUP DELTA STAGED; no phone writes', flush=True)
