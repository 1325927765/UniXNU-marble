"""Create a local, owned HFSX mount fixture on macOS, never a phone image."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

def run(*args):
    return subprocess.check_output([str(a) for a in args],stderr=subprocess.STDOUT,text=True)

ap=argparse.ArgumentParser(description=__doc__)
ap.add_argument('--work',type=Path,required=True)
ap.add_argument('--size-mib',type=int,choices=(16,64),default=16)
args=ap.parse_args()
work=args.work.expanduser().resolve()
if work.exists(): raise SystemExit('Use a fresh fixture directory')
work.mkdir(parents=True)
image=work/'fixture.sparseimage'; mount=work/'mounted'; mount.mkdir()
print(run('hdiutil','create','-size',str(args.size_mib)+'m','-layout','NONE','-fs','JHFSX',
          '-volname','MarbleMountProbe','-type','SPARSE',image),flush=True)
print(run('hdiutil','attach','-nobrowse','-mountpoint',mount,image),flush=True)
marker=b'Marble HFSX mount probe v1\n'
try:
    (mount/'mount-probe.txt').write_bytes(marker)
    print(run('diskutil','verifyVolume',mount),flush=True)
finally:
    print(run('hdiutil','detach',mount),flush=True)
raw=work/'fixture.cdr'
print(run('hdiutil','convert','-format','UDTO','-o',raw,image),flush=True)
data=raw.read_bytes()
assert data[1024:1026]==b'HX' and data[512:520]!=b'EFI PART'
print(run('hdiutil','attach','-readonly','-nobrowse','-mountpoint',mount,raw),flush=True)
try:
    assert (mount/'mount-probe.txt').read_bytes()==marker
finally:
    print(run('hdiutil','detach',mount),flush=True)
report={'raw_image':str(raw),'image_bytes':len(data),'image_sha256':hashlib.sha256(data).hexdigest(),
        'hfsx_signature':data[1024:1026].hex(),'marker':'mount-probe.txt',
        'marker_sha256':hashlib.sha256(marker).hexdigest(),'macos_readonly_mount_and_marker':'PASS',
        'guest_xnu_mount_tested':False,'contains_ios_userspace':False,'phone_storage_modified':False}
(work/'report.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report,indent=2))
