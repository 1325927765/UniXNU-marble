"""Add the minimal iOS runtime properties to an existing Marble QEMU ADT.

The output remains QEMU-only.  The synthetic ECID is a fixed test value and
is not derived from the phone.
"""
from __future__ import annotations

import argparse
import struct
import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "research/reference-ios-sweet/tools"))
import adt  # noqa: E402


U32 = lambda value: struct.pack("<I", value)
U64 = lambda value: struct.pack("<Q", value)
SYNTHETIC_MARBLE_ECID = 0x4D4152424C450001


def child(root, name):
    return next((item for item in root.children if item.name == name), None)


def set_prop(node, name, value):
    found = False
    props = []
    for prop_name, flags, old_value in node.props:
        if prop_name == name:
            props.append((prop_name, flags, value))
            found = True
        else:
            props.append((prop_name, flags, old_value))
    if not found:
        props.append((name, 0, value))
    node.props = props


parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("source", type=Path)
parser.add_argument("output", type=Path)
args = parser.parse_args()

root, _ = adt.parse(args.source.read_bytes())
chosen = child(root, "chosen")
defaults = child(root, "defaults")
if chosen is None or defaults is None:
    raise SystemExit("ADT must contain /chosen and /defaults")

chosen_values = {
    "display-scale": U32(3),
    "unique-chip-id": U64(SYNTHETIC_MARBLE_ECID),
    "chip-id": U32(0x8015),
    "certificate-production-status": U32(0),
    "effective-production-status-ap": U32(0),
    "certificate-security-mode": U32(1),
    "effective-security-mode-sep": U32(1),
}
for key, value in chosen_values.items():
    set_prop(chosen, key, value)
set_prop(defaults, "no-effaceable-storage", U32(1))

args.output.parent.mkdir(parents=True, exist_ok=True)
args.output.write_bytes(adt.serialize(root))

check, _ = adt.parse(args.output.read_bytes())
check_chosen = child(check, "chosen")
check_defaults = child(check, "defaults")
assert check_chosen is not None and check_defaults is not None
for key, value in chosen_values.items():
    assert check_chosen.prop(key) == value, key
assert check_defaults.prop("no-effaceable-storage") == U32(1)
print(
    f"wrote {args.output}: display-scale=3, synthetic ECID=0x{SYNTHETIC_MARBLE_ECID:x}, "
    "chip-id=0x8015, no-effaceable-storage=1"
)
