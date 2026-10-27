"""Exercise preference merge and exact restore on a disposable Mac fixture."""
import pathlib
import plistlib
import subprocess
import sys
import tempfile

with tempfile.TemporaryDirectory(prefix='marble-setup-test-') as temp:
    base = pathlib.Path(temp)
    root = base/'root'
    version = root/'System/Library/CoreServices'
    version.mkdir(parents=True)
    (version/'SystemVersion.plist').write_bytes(plistlib.dumps(
        dict(ProductVersion='16.7.16', ProductBuildVersion='20H392')))
    prefs = root/'private/var/mobile/Library/Preferences'
    prefs.mkdir(parents=True)
    original = {}
    for name in ('com.apple.purplebuddy', 'com.apple.purplebuddy.notbackedup', 'com.apple.springboard'):
        path = prefs/(name+'.plist')
        original[name] = plistlib.dumps(dict(UnknownKeep=42, SetupDone=False), fmt=plistlib.FMT_BINARY)
        path.write_bytes(original[name])
    script = pathlib.Path(__file__).with_name('prepare-marble-ios16-setup-skip.py')
    cmd = [sys.executable, str(script), '--root', str(root), '--backup-dir', str(base/'backup')]
    subprocess.run(cmd+['--apply'], check=True, stdout=subprocess.DEVNULL)
    for name in original:
        assert plistlib.loads((prefs/(name+'.plist')).read_bytes())['UnknownKeep'] == 42
    assert plistlib.loads((prefs/'com.apple.purplebuddy.plist').read_bytes())['SetupDone'] is True
    subprocess.run(cmd+['--restore'], check=True)
    for name in original:
        assert (prefs/(name+'.plist')).read_bytes() == original[name]
    print('SETUP PREF MERGE/EXACT RESTORE PASS')
