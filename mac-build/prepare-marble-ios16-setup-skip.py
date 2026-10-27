"""Merge reversible Setup Assistant preferences in an offline iOS 16 HFS root.

This changes setup UI preferences only. It does not change activation records.
Dry-run by default; --apply needs a fresh backup directory outside the root.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import plistlib
import stat
import sys
import uuid

PREFS = {
    'com.apple.purplebuddy': dict(SetupDone=True, SetupFinishedAllSteps=True,
        SetupVersion=11, daemonizeNeedsToRun=False),
    'com.apple.purplebuddy.notbackedup': {k: False for k in (
        'ShouldRunDiagnosticsMiniBuddy', 'ShouldRunHSA2MiniBuddy',
        'ShouldRunKeychainSyncMiniBuddy', 'ShouldRunMesaMiniBuddy',
        'ShouldRunPaymentMiniBuddy', 'ShouldRunStandardMiniBuddy', 'SilentICDPUpgrade')},
    'com.apple.springboard': dict(MCForceShowCloudConfigurationUI=False),
}
def sha(data): return hashlib.sha256(data).hexdigest()
def checked(root, relative):
    p = root/relative
    assert p.resolve().is_relative_to(root), 'path leaves mounted root'
    assert not p.is_symlink(), 'refusing symlink preference'
    return p
def atomic_save(dest, data, item):
    temp = dest.with_name(dest.name+'.marble-'+uuid.uuid4().hex+'.tmp')
    try:
        with temp.open('xb') as f:
            f.write(data); f.flush(); os.fsync(f.fileno())
        os.chown(temp, item['uid'], item['gid']); os.chmod(temp, item['mode'])
        os.replace(temp, dest)
        fd = os.open(dest.parent, os.O_RDONLY)
        try: os.fsync(fd)
        finally: os.close(fd)
    finally:
        temp.unlink(missing_ok=True)

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root', type=Path, required=True)
    p.add_argument('--backup-dir', type=Path)
    p.add_argument('--apply', action='store_true')
    p.add_argument('--restore', action='store_true')
    a = p.parse_args()
    root = a.root.resolve(strict=True)
    version = plistlib.loads((root/'System/Library/CoreServices/SystemVersion.plist').read_bytes())
    assert (version['ProductVersion'], version['ProductBuildVersion']) == ('16.7.16', '20H392')
    assert not (a.apply and a.restore)
    if a.restore:
        assert a.backup_dir
        saved = json.loads((a.backup_dir/'manifest.json').read_text())
        for item in saved['files']:
            dest = checked(root, item['path'])
            if not dest.exists():
                assert not item['existed'], 'original preference unexpectedly missing'
            else:
                assert dest.is_file() and sha(dest.read_bytes()) in (item['after_sha256'], item['before_sha256']), 'preference changed since apply'
            if item['existed']:
                original = (a.backup_dir/item['path']).read_bytes()
                assert sha(original) == item['before_sha256']
        for item in saved['files']:
            dest = checked(root, item['path'])
            if not item['existed']:
                dest.unlink(missing_ok=True)
            else:
                atomic_save(dest, (a.backup_dir/item['path']).read_bytes(), item)
        print('Restored original setup preferences after current-hash verification')
        return
    planned = []
    for name, updates in PREFS.items():
        rel = 'private/var/mobile/Library/Preferences/'+name+'.plist'
        dest = checked(root, rel)
        assert dest.parent.is_dir(), 'expected mobile preferences directory'
        existed = dest.exists()
        original = dest.read_bytes() if existed else b''
        if existed:
            st = dest.stat(); assert stat.S_ISREG(st.st_mode)
            data = plistlib.loads(original); assert isinstance(data, dict)
            uid, gid, mode = st.st_uid, st.st_gid, stat.S_IMODE(st.st_mode)
        else:
            data = {}; uid, gid, mode = 501, 501, 0o600
        data.update(updates)
        fmt = plistlib.FMT_BINARY if original.startswith(b'bplist') or not existed else plistlib.FMT_XML
        changed = plistlib.dumps(data, fmt=fmt, sort_keys=False)
        planned.append((dict(path=rel, existed=existed, before_sha256=sha(original),
            after_sha256=sha(changed), uid=uid, gid=gid, mode=mode,
            updated_keys=sorted(updates)), original, changed))
    report = dict(product_version='16.7.16', product_build='20H392',
                  scope='Setup UI preferences only; activation records unchanged',
                  files=[item for item, _, _ in planned])
    if a.apply:
        assert a.backup_dir
        backup = a.backup_dir.resolve()
        assert not backup.is_relative_to(root) and not backup.exists()
        backup.mkdir(parents=True, mode=0o700)
        for item, original, _ in planned:
            if item['existed']:
                dest = backup/item['path']; dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(original); os.chmod(dest, 0o600)
                assert sha(dest.read_bytes()) == item['before_sha256']
        (backup/'manifest.json').write_text(json.dumps(report, indent=2)+'\n')
        try:
            for item, _, changed in planned:
                dest = checked(root, item['path'])
                atomic_save(dest, changed, item)
                assert sha(dest.read_bytes()) == item['after_sha256']
        except Exception:
            for item, original, _ in planned:
                dest = checked(root, item['path'])
                try:
                    if item['existed']: atomic_save(dest, original, item)
                    else: dest.unlink(missing_ok=True)
                except Exception as rollback_error:
                    print('Backup retained; rollback error: '+str(rollback_error), file=sys.stderr)
            raise
    print(json.dumps(report, indent=2))
    print('APPLIED' if a.apply else 'DRY RUN; no preferences changed')

if __name__ == '__main__': main()
