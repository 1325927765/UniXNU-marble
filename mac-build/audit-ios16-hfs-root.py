"""Inspect the prepared iPhone iOS 16 HFSX root through a read-only Mac mount."""
import argparse
import hashlib
import json
from pathlib import Path
import plistlib
import struct
import subprocess

ap=argparse.ArgumentParser(description=__doc__)
ap.add_argument('--image',type=Path,required=True)
ap.add_argument('--work',type=Path,required=True)
args=ap.parse_args()
image=args.image.expanduser().resolve(); work=args.work.expanduser().resolve()
if work.exists(): raise SystemExit('Use a fresh audit directory')
work.mkdir(parents=True); mount=work/'mounted'; mount.mkdir()
with image.open('rb') as f:
    prefix=f.read(4096)
assert image.stat().st_size==16*1024**3
assert prefix[1024:1026]==b'HX' and prefix[512:520]!=b'EFI PART'
blocksize,total=struct.unpack_from('>II',prefix,1024+40)
assert blocksize in (4096,8192) and blocksize*total==image.stat().st_size
def run(*cmd):
    return subprocess.check_output([str(c) for c in cmd],stderr=subprocess.STDOUT,text=True)
print(run('hdiutil','attach','-readonly','-nobrowse','-mountpoint',mount,image),flush=True)
try:
    version=plistlib.loads((mount/'System/Library/CoreServices/SystemVersion.plist').read_bytes())
    assert version['ProductVersion']=='16.7.16' and version['ProductBuildVersion']=='20H392'
    launchd=(mount/'sbin/launchd').read_bytes()
    assert struct.unpack_from('<II',launchd)==(0xfeedfacf,0x100000c)
    checks={
        'launchd':(mount/'sbin/launchd').is_file(),
        'dyld':(mount/'usr/lib/dyld').is_file(),
        'os_cryptex':(mount/'private/preboot/Cryptexes/OS').is_dir(),
        'app_cryptex':(mount/'private/preboot/Cryptexes/App').is_dir(),
        'shared_cache':any((mount/'System/Library/Caches/com.apple.dyld').glob('dyld_shared_cache_arm64*'))
    }
    assert all(checks.values())
    fsck=run('diskutil','verifyVolume',mount)
    (work/'verify-volume.log').write_text(fsck)
    report={'source_image':str(image),'image_bytes':image.stat().st_size,
        'filesystem':'HFSX','allocation_block_bytes':blocksize,'allocation_blocks':total,
        'ios_version':version,'source_device_family':'iPhone X (iPhone10,3/iPhone10,6) restore input',
        'launchd_sha256':hashlib.sha256(launchd).hexdigest(),
        'launchd_cpu_subtype':struct.unpack_from('<I',launchd,8)[0],
        'checks':checks,'macos_readonly_mount':'PASS','macos_verify_volume':'PASS',
        'phone_ios_root_mounted':False,'ios_userspace_booted':False}
    (work/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2),flush=True)
finally:
    print(run('hdiutil','detach',mount),flush=True)
