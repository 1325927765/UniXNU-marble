"""Create a separate ADT variant with the iOS main display scale property."""
import argparse
import struct
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "research/reference-ios-sweet/tools"))
import adt  # noqa: E402

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("source", type=Path)
parser.add_argument("output", type=Path)
parser.add_argument("--scale", type=int, default=3)
args = parser.parse_args()
if args.scale < 1 or args.scale > 10:
    parser.error("scale must be between 1 and 10")

root, _ = adt.parse(args.source.read_bytes())
chosen = next((child for child in root.children if child.name == "chosen"), None)
if chosen is None:
    raise SystemExit("ADT has no /chosen node")
old = chosen.prop("display-scale")
value = struct.pack("<I", args.scale)
if old is None:
    chosen.props.append(("display-scale", 0, value))
elif old != value:
    chosen.props = [(name, flags, value if name == "display-scale" else prop)
                    for name, flags, prop in chosen.props]
args.output.write_bytes(adt.serialize(root))
check, _ = adt.parse(args.output.read_bytes())
assert next(child for child in check.children if child.name == "chosen").prop("display-scale") == value
print(f"wrote {args.output}: /chosen/display-scale={args.scale}")
