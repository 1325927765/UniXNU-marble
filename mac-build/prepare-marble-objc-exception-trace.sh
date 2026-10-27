#!/bin/bash
set -euo pipefail

base=/tmp/ios16-root-marble-base.cdr
modified=/tmp/ios16-root-backboardd-stderr-v3.cdr
mount=/tmp/ios16-root-backboardd-stderr-v3-mount
delta=/tmp/ios16-root-backboardd-stderr-v3.delta
expected=495d21d62b65da4e44dd544e85a0760d850b4b776f50de52b7c35a2e16b131bd

for path in "$mount" "$delta" "$delta.zst"; do
	if [[ -e "$path" ]]; then echo "Refusing to overwrite: $path" >&2; exit 1; fi
done
actual=$(shasum -a 256 "$base" | awk '{print $1}')
if [[ "$actual" != "$expected" ]]; then echo "Base image hash mismatch: $actual" >&2; exit 1; fi

# APFS clone keeps this experimental image separate without duplicating 16 GiB.
if [[ -e "$modified" ]]; then
	actual=$(shasum -a 256 "$modified" | awk '{print $1}')
	if [[ "$actual" != "$expected" ]]; then echo "Existing clone was changed: $actual" >&2; exit 1; fi
else
	cp -c -p "$base" "$modified"
fi
mkdir "$mount"
attached=0
cleanup() {
	if [[ $attached = 1 ]]; then hdiutil detach "$mount" >/dev/null 2>&1 || true; fi
	rmdir "$mount" 2>/dev/null || true
}
trap cleanup EXIT
hdiutil attach -readwrite -owners off -nobrowse -mountpoint "$mount" "$modified" >/dev/null
attached=1
sudo python3 - "$mount/System/Library/LaunchDaemons/com.apple.backboardd.plist" <<'PY'
import plistlib, sys
from pathlib import Path
p = Path(sys.argv[1])
data = plistlib.loads(p.read_bytes())
env = data.setdefault('EnvironmentVariables', {})
if not isinstance(env, dict):
    raise SystemExit('EnvironmentVariables is not a dictionary')
env['OBJC_PRINT_EXCEPTIONS'] = 'YES'
# Preserve runtime diagnostics that launchd would otherwise send to a null sink.
data['StandardErrorPath'] = '/dev/console'
p.write_bytes(plistlib.dumps(data, fmt=plistlib.FMT_BINARY, sort_keys=False))
print('set OBJC_PRINT_EXCEPTIONS=YES and StandardErrorPath=/dev/console in', p)
PY
plutil -lint "$mount/System/Library/LaunchDaemons/com.apple.backboardd.plist"
hdiutil detach "$mount" >/dev/null
attached=0
rmdir "$mount"
trap - EXIT

python3 /tmp/make-marble-ios-root-delta.py "$base" "$modified" "$delta"
/opt/homebrew/bin/zstd -1 -f "$delta" -o "$delta.zst"
shasum -a 256 "$modified" "$delta" "$delta.zst"
ls -lh "$modified" "$delta" "$delta.zst"
