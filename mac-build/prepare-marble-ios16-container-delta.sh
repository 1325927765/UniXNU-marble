#!/bin/bash
set -euo pipefail

source=/tmp/ios16-root-marble-base.cdr.zst
base=/tmp/ios16-root-marble-base.cdr
modified=/tmp/ios16-root-marble-containerfix.cdr
mount=/tmp/ios16-root-marble-mount
delta=/tmp/ios16-root-marble-containerfix.delta
expected=495d21d62b65da4e44dd544e85a0760d850b4b776f50de52b7c35a2e16b131bd

for path in "$base" "$modified" "$delta" "$mount"; do
	if [ -e "$path" ]; then
		echo "Refusing to overwrite existing path: $path" >&2
		exit 1
	fi
done

/opt/homebrew/bin/zstd -t "$source"
/opt/homebrew/bin/zstd -d -q -c "$source" > "$base"
test "$(stat -f %z "$base")" = 17179869184
actual=$(shasum -a 256 "$base" | awk '{print $1}')
if [ "$actual" != "$expected" ]; then
	echo "Base image SHA-256 mismatch: $actual" >&2
	exit 1
fi
cp -p "$base" "$modified"
mkdir "$mount"

attached=0
cleanup_mount() {
	if [ "$attached" = 1 ]; then
		hdiutil detach "$mount" >/dev/null || true
	fi
}
trap cleanup_mount EXIT
hdiutil attach -readwrite -nobrowse -mountpoint "$mount" "$modified"
attached=1
umask 022
dirs=(
	"$mount/private/var/containers"
	"$mount/private/var/containers/Bundle"
	"$mount/private/var/containers/Data/System"
	"$mount/private/var/containers/Shared/SystemGroup"
	"$mount/private/var/containers/Temp"
)
for path in "${dirs[@]}"; do
	mkdir -p "$path"
	sudo chown 0:0 "$path"
	chmod 755 "$path"
done
hdiutil detach "$mount"
attached=0
rmdir "$mount"
trap - EXIT

python3 /tmp/make-marble-ios-root-delta.py \
	"$base" "$modified" "$delta"
/opt/homebrew/bin/zstd -1 -f "$delta" -o "$delta.zst"
shasum -a 256 "$modified" "$delta" "$delta.zst"
ls -lh "$modified" "$delta" "$delta.zst"
