#!/bin/bash
set -euo pipefail
base=/tmp/ios16-root-marble-base.cdr
mount=/tmp/ios16-root-audit-codex
if [[ -e "$mount" ]]; then
	echo "Refusing to reuse existing mount path: $mount" >&2
	exit 1
fi
mkdir "$mount"
attached=0
cleanup() {
	if [[ $attached = 1 ]]; then hdiutil detach "$mount" >/dev/null 2>&1 || true; fi
	rmdir "$mount" 2>/dev/null || true
}
trap cleanup EXIT
hdiutil attach -readonly -nobrowse -mountpoint "$mount" "$base" >/dev/null
attached=1
echo '--- private/var directories ---'
find "$mount/private/var" -maxdepth 2 -type d -print | head -100 || true
echo '--- backboardd plist/binary candidates ---'
find -L "$mount" \( -iname '*backboardd*.plist' -o -iname 'backboardd' -o -iname 'logd' -o -iname '*logd*.plist' \) -print 2>/dev/null | head -50 || true
echo '--- standard service paths ---'
for path in \
	"$mount/usr/libexec/backboardd" "$mount/usr/libexec/logd" \
	"$mount/sbin/backboardd" "$mount/sbin/logd" \
	"$mount/System/Library/LaunchDaemons/com.apple.backboardd.plist" \
	"$mount/System/Library/LaunchDaemons/com.apple.logd.plist"; do
	if [[ -e "$path" ]]; then ls -l "$path"; else echo "missing: $path"; fi
done
hdiutil detach "$mount" >/dev/null
attached=0
