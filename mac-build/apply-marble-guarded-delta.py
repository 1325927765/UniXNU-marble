"""Apply/restore a small HFS block edit only after checking every preimage.

Target is fixed to an unmounted marble userdata partition. Dry-run by default.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('delta', type=Path)
p.add_argument('--adb', default='adb')
p.add_argument('--serial', required=True)
p.add_argument('--apply', action='store_true')
p.add_argument('--rollback', action='store_true')
p.add_argument('--repair-interrupted', action='store_true', help='Rollback only: restore a logged interrupted chunk from its verified backup')
a = p.parse_args()
def adb(*args):
    return subprocess.check_output([a.adb,'-s',a.serial,*args], stderr=subprocess.PIPE)
def shell(cmd): return adb('shell',cmd).decode().strip()
def sha(data): return hashlib.sha256(data).hexdigest()
def unmounted():
    assert shell('getprop ro.product.device') == 'marble'
    block = shell('readlink -f /dev/block/by-name/userdata')
    assert block.startswith('/dev/block/')
    assert all(row.split()[0] not in (block,'/dev/block/by-name/userdata')
               for row in shell('cat /proc/mounts').splitlines())
def read_range(offset,length):
    data = adb('exec-out','dd if=/dev/block/by-name/userdata bs=1048576 '
        f'iflag=count_bytes,skip_bytes count={length} skip={offset} 2>/dev/null')
    assert len(data) == length, 'short device read'
    return data
manifest_bytes = (a.delta/'manifest.json').read_bytes()
manifest_sha = sha(manifest_bytes)
manifest = json.loads(manifest_bytes)
assert not a.repair_interrupted or a.rollback
progress_path = a.delta/'device-apply-progress.json'
prior = json.loads(progress_path.read_text()) if progress_path.exists() else {}
assert manifest['format'] == 'marble-guarded-blocks-v1' and manifest['volume_bytes'] == 16*1024**3
records = manifest['records']; assert 0 < len(records) <= 256
assert manifest['changed_bytes'] == len(records)*1024**2
previous_end = 0
source, target = ('after','before') if a.rollback else ('before','after')
for r in records:
    offset, length = r['offset'],r['length']
    assert length == 1024**2 and offset % length == 0 and previous_end <= offset
    assert offset+length <= manifest['volume_bytes']; previous_end = offset+length
    for side in ('before','after'):
        path = a.delta/r[side+'_file']
        assert path.resolve().parent == a.delta.resolve() and path.is_file()
        data = path.read_bytes(); assert len(data) == length and sha(data) == r[side+'_sha256']
unmounted()
header = read_range(0,4096)
assert header[1024:1026] in (b'H+',b'HX')
states = {}
for n,r in enumerate(records):
    current = sha(read_range(r['offset'],r['length']))
    state = next((side for side in ('before','after') if current == r[side+'_sha256']), None)
    if state is None:
        assert (a.repair_interrupted and prior.get('manifest_sha256') == manifest_sha and
                prior.get('pending_offset') == r['offset'] and prior.get('direction') == 'before->after'), f'unknown preimage record {n}'
    states[r['offset']] = current
print(f'ALL {len(records)} device states validated; target={target}',flush=True)
if not a.apply:
    print('DRY RUN; no phone files or blocks changed')
    raise SystemExit(0)
unmounted()
remote = shell('mktemp -d /tmp/marble-setup-blocks.XXXXXX')
assert remote.startswith('/tmp/marble-setup-blocks.') and all(c.isalnum() or c in '/.-' for c in remote)
completed = []
def progress(pending=None):
    data = json.dumps(dict(manifest_sha256=manifest_sha,
        direction=source+'->'+target, verified_offsets=completed, pending_offset=pending),indent=2)+'\n'
    temp = progress_path.with_suffix('.json.tmp')
    with temp.open('w') as f:
        f.write(data); f.flush(); os.fsync(f.fileno())
    os.replace(temp, progress_path)
try:
    for n,r in enumerate(records):
        if states[r['offset']] == r[target+'_sha256']:
            completed.append(r['offset']); continue
        filename = r[target+'_file']; remote_file = remote+'/'+filename
        adb('push',str(a.delta/filename),remote_file)
        assert sha(read_range(r['offset'],r['length'])) == states[r['offset']]
        progress(r['offset'])
        shell(f'dd if={remote_file} of=/dev/block/by-name/userdata bs=4096 '
              f'seek={r["offset"]//4096} count={r["length"]//4096} conv=notrunc,fsync')
        assert sha(read_range(r['offset'],r['length'])) == r[target+'_sha256'], 'write readback mismatch'
        completed.append(r['offset'])
        progress()
        print(f'Written and readback verified {n+1}/{len(records)}',flush=True)
    for r in records: assert sha(read_range(r['offset'],r['length'])) == r[target+'_sha256']
    print('ALL CHANGED BLOCKS VERIFIED; offline preference edit complete',flush=True)
finally:
    # This removes only the exact mktemp directory's known uploaded chunk files.
    try:
        for r in records:
            shell('rm -f '+remote+'/'+r[target+'_file'])
        shell('rmdir '+remote)
    except Exception as cleanup_error:
        print('RAM staging cleanup failed; original operation status retained: '+str(cleanup_error), file=sys.stderr)
