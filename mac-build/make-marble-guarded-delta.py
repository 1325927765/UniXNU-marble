"""Create bounded forward/rollback block sets from an offline HFS preference edit."""
import argparse
import hashlib
import json
from pathlib import Path

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('before', type=Path)
p.add_argument('after', type=Path)
p.add_argument('out', type=Path)
p.add_argument('--max-changed-mib', type=int, default=256)
a = p.parse_args()
assert a.before.resolve() != a.after.resolve()
size = a.before.stat().st_size
assert size == a.after.stat().st_size and size == 16*1024**3
assert not a.out.exists()
a.out.mkdir(parents=True)
def sha(b): return hashlib.sha256(b).hexdigest()
before_sha, after_sha = hashlib.sha256(), hashlib.sha256()
items = []; changed_bytes = 0; chunk_size = 1024**2
with a.before.open('rb') as left, a.after.open('rb') as right:
    for offset in range(0, size, chunk_size):
        before, after = left.read(chunk_size), right.read(chunk_size)
        assert len(before) == len(after) == chunk_size
        before_sha.update(before); after_sha.update(after)
        if before == after: continue
        changed_bytes += chunk_size
        assert changed_bytes <= a.max_changed_mib*1024**2, 'unexpectedly large filesystem delta'
        name = f'{offset:012x}'
        (a.out/(name+'.before')).write_bytes(before)
        (a.out/(name+'.after')).write_bytes(after)
        items.append(dict(offset=offset, length=chunk_size, before_file=name+'.before',
                          after_file=name+'.after', before_sha256=sha(before), after_sha256=sha(after)))
manifest = dict(format='marble-guarded-blocks-v1', volume_bytes=size, chunk_bytes=chunk_size,
    before_sha256=before_sha.hexdigest(), after_sha256=after_sha.hexdigest(),
    changed_bytes=changed_bytes, records=items)
(a.out/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
print(json.dumps({k:v for k,v in manifest.items() if k!='records'},indent=2))
print('Changed chunks:',len(items))
