"""Adapt the proven iOS 16 AppleKeyStore stand-in to a Marble XNU tree.

Usage:
  python3 integrate-marble8796-keystore.py 0038-sweet-applekeystore.patch \
      0055-sweet-aks-ext-state-sampler-depth.patch /path/to/xnu
"""
from __future__ import annotations

import argparse
from pathlib import Path


def extract_added_file(patch: str, suffix: str) -> str:
    target = None
    lines = []
    collecting = False
    for line in patch.splitlines(keepends=True):
        if line.startswith("--- "):
            if collecting:
                break
            target = None
        elif line.startswith("+++ b/"):
            target = line[6:].strip()
            collecting = target.endswith(suffix)
        elif collecting and line.startswith("+") and not line.startswith("+++"):
            lines.append(line[1:])
    if not lines:
        raise RuntimeError(f"new file {suffix} was not found in reference patch")
    return "".join(lines)


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one patch point, found {count}")
    return text.replace(old, new, 1)


parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("base_patch", type=Path)
parser.add_argument("ext_patch", type=Path)
parser.add_argument("xnu", type=Path)
args = parser.parse_args()

xnu = args.xnu.resolve()
if not xnu.is_dir():
    raise SystemExit(f"XNU tree is missing: {xnu}")

base_patch_text = args.base_patch.read_text()
ext_patch_text = args.ext_patch.read_text()
for marker in ("kAKSGetExtDeviceState", "kAKSAssertConsume"):
    if marker not in ext_patch_text:
        raise RuntimeError(f"{args.ext_patch}: expected marker {marker} is missing")
source = extract_added_file(base_patch_text, "SweetKeyStore.cpp")
source = source.replace("SWEET", "MARBLE").replace("Sweet", "Marble").replace("sweet", "marble")

# Apply the functional parts of sweet 0055.  Sampler changes in that patch are
# unrelated and deliberately excluded.
source = replace_once(
    source,
    "\tkAKSGetDeviceState   = 17,\n",
    "\tkAKSGetDeviceState   = 17,\n"
    "\tkAKSGetExtDeviceState = 35,     /* aks_get_extended_device_state */\n",
    "AKS enum 35",
)
source = replace_once(
    source,
    "\tkAKSNotifyStateSet   = 102,\n",
    "\tkAKSAssertConsume    = 101,     /* aks_assert_consume */\n"
    "\tkAKSNotifyStateSet   = 102,\n",
    "AKS enum 101",
)
source = replace_once(
    source,
    "\tcase kAKSAssertDrop:\n",
    "\tcase kAKSAssertDrop:\n\tcase kAKSAssertConsume:\n",
    "AKS selector 101",
)
source = replace_once(
    source,
    "\tcase kAKSGetDeviceState:\n",
    "\tcase kAKSGetDeviceState:\n\tcase kAKSGetExtDeviceState:\n",
    "AKS selector 35",
)

driver = xnu / "iokit/Kernel/arm/MarbleKeyStore.cpp"
if driver.exists() and driver.read_text() != source:
    raise RuntimeError(f"refusing to overwrite modified {driver}")
driver.parent.mkdir(parents=True, exist_ok=True)
driver.write_text(source)

files_arm = xnu / "iokit/conf/files.arm64"
files_text = files_arm.read_text()
driver_line = "iokit/Kernel/arm/MarbleKeyStore.cpp                                optional iokitcpp\n"
if driver_line not in files_text:
    anchor = next(
        (line for line in files_text.splitlines(keepends=True)
         if line.startswith("iokit/Kernel/arm/MarbleEntitlements.cpp")),
        None,
    )
    if anchor is None:
        raise RuntimeError("files.arm64: MarbleEntitlements.cpp anchor is missing")
    files_arm.write_text(files_text.replace(anchor, anchor + driver_line, 1))

table = xnu / "iokit/KernelConfigTables.cpp"
table_text = table.read_text()
if "'IOClass'         = AppleKeyStore;" not in table_text:
    marker = "#if defined(ARM64_BOARD_CONFIG_MARBLE)"
    start = table_text.index(marker)
    end = table_text.index("#endif", start)
    personality = (
        "    \"   {\"\n"
        "    \"     'IOClass'         = AppleKeyStore;\"\n"
        "    \"     'IOProviderClass' = IOResources;\"\n"
        "    \"     'IOMatchCategory' = AppleKeyStore;\"\n"
        "    \"   },\"\n"
    )
    table.write_text(table_text[:end] + personality + table_text[end:])

print(f"installed {driver} ({len(source)} bytes), selectors 35/101 included")
