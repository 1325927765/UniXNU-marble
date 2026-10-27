"""Read the unmounted userdata HFS volume through recovery ADB to a host backup."""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import subprocess
import time

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--adb', default='adb')
p.add_argument('--serial', required=True)
p.add_argument('--out', type=Path, required=True)
p.add_argument('--resume', action='store_true', help='Validate head/tail and resume an aligned partial host copy')
a = p.parse_args()
def read(*args):
    return subprocess.check_output([a.adb, '-s', a.serial, *args], stderr=subprocess.DEVNULL)
assert read('shell', 'getprop ro.product.device').strip() == b'marble'
block = read('shell', 'readlink -f /dev/block/by-name/userdata').decode().strip()
mounts = read('shell', 'cat /proc/mounts').decode()
assert all(line.split()[0] not in (block, '/dev/block/by-name/userdata') for line in mounts.splitlines())
head = read('exec-out', 'dd if=/dev/block/by-name/userdata bs=4096 count=1 2>/dev/null')
assert len(head) == 4096 and head[1024:1026] in (b'H+', b'HX')
blocksize, count = struct.unpack_from('>II', head, 1064)
size = blocksize * count
assert blocksize == 4096 and 0 < size <= 32*1024**3 and size % 1048576 == 0
a.out.parent.mkdir(parents=True, exist_ok=True)
partial = a.out.with_suffix(a.out.suffix+'.partial')
assert not a.out.exists()
total = 0
h = hashlib.sha256()
if a.resume:
    assert partial.is_file()
    total = partial.stat().st_size
    assert 4096 <= total < size and total % 512 == 0
    with partial.open('rb') as f:
        assert f.read(4096) == head
        f.seek(total-4096); tail = f.read(4096)
        assert tail == read('exec-out', 'dd if=/dev/block/by-name/userdata bs=4096 '
                           'iflag=count_bytes,skip_bytes count=4096 skip='+str(total-4096)+' 2>/dev/null')
        f.seek(0)
        while chunk := f.read(8*1024**2): h.update(chunk)
    print(f'Resuming verified partial at {total/1024**3:.2f} GiB', flush=True)
else:
    assert not partial.exists()
cmd = [a.adb, '-s', a.serial, 'exec-out',
       'dd if=/dev/block/by-name/userdata bs=1048576 iflag=count_bytes,skip_bytes '
       'skip='+str(total)+' count='+str(size-total)+' 2>/dev/null']
proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
last = time.monotonic()
with partial.open('ab' if a.resume else 'xb') as f:
    while chunk := proc.stdout.read(8*1024**2):
        total += len(chunk)
        if total > size:
            proc.kill(); raise RuntimeError('stream exceeds HFS volume')
        f.write(chunk); h.update(chunk)
        now = time.monotonic()
        if now-last >= 15:
            print(f'Copied {total/1024**3:.2f}/{size/1024**3:.2f} GiB', flush=True); last = now
error = proc.stderr.read().decode(errors='replace')
assert proc.wait() == 0, error
assert total == size
with partial.open('rb') as f: assert f.read(4096) == head
partial.rename(a.out)
report = dict(bytes=total, sha256=h.hexdigest(), source='unmounted userdata HFS volume',
              host_file=str(a.out), method='read-only ADB dd stdout', phone_writes=False)
a.out.with_suffix(a.out.suffix+'.json').write_text(json.dumps(report, indent=2)+'\n')
print(json.dumps(report, indent=2), flush=True)
