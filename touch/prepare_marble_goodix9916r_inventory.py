#!/usr/bin/env python3
"""Inventory the saved Marble Goodix 9916R DT node and extracted vendor blobs.

Read-only: this tool does not access ADB/USB, probe SPI, or write to a device.
Pass a host-side extracted vendor partition/root to inventory likely firmware,
configuration, and kernel-module artifacts. The report is stdout-only unless
--json-out is explicitly supplied.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re


LAB = Path(__file__).resolve().parents[1]
DEFAULT_DTS = LAB / "research/hardware-live-20261023-connected/marble-live.dts"
UPSTREAM = {
    "repository": "https://github.com/MiCode/Xiaomi_Kernel_OpenSource",
    "marble_branch": "marble-s-oss",
    "marble_commit": "48952ed36228217531482b39d5bef13e7fd808ec",
    "ruby_branch": "ruby-s-oss",
    "ruby_commit": "914ba8403bb3a957ed37b99dcecdbafce9d16121",
    "ruby_spi_source": "drivers/input/touchscreen/goodix_9916r/goodix_brl_spi.c",
    "ruby_core_source": "drivers/input/touchscreen/goodix_9916r/goodix_ts_core.c",
    "marble_spi_source": "drivers/input/touchscreen/goodix_9916/goodix_brl_spi.c",
}


def balanced_node(text: str, compatible: str) -> str:
    marker = f'compatible = "{compatible}"'
    pos = text.find(marker)
    if pos < 0 or text.find(marker, pos + 1) >= 0:
        raise ValueError(f"expected exactly one {marker!r} in DTS")
    start = text.rfind("{", 0, pos)
    if start < 0:
        raise ValueError("could not find node opening brace")
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
    raise ValueError("unterminated DTS node")


def properties(block: str) -> dict[str, str]:
    # This deliberately records only scalar/string/angle-list properties.
    result = {}
    for name, value in re.findall(r"^\s*([A-Za-z0-9,_-]+)\s*=\s*([^;]+);", block, re.M):
        result[name] = value.strip()
    return result


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def find_named(root: Path, names: set[str]) -> list[Path]:
    matches = []
    for path in root.rglob("*"):
        if path.is_file() and path.name in names:
            matches.append(path)
    return sorted(matches)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dts", type=Path, default=DEFAULT_DTS)
    parser.add_argument("--vendor-root", type=Path,
                        help="host-side extracted Android vendor/vendor_boot root; never a device path")
    parser.add_argument("--json-out", type=Path,
                        help="optional report file; default prints JSON to stdout")
    args = parser.parse_args()

    dts = args.dts.resolve(strict=True)
    block = balanced_node(dts.read_text(encoding="utf-8", errors="replace"), "goodix,9916r-spi")
    props = properties(block)
    required = ("spi-max-frequency", "interrupts", "goodix,irq-gpio", "goodix,reset-gpio",
                "goodix,panel-max-x", "goodix,panel-max-y", "goodix,firmware-name",
                "goodix,config-name")
    missing_properties = [key for key in required if key not in props]
    vendor_matches = []
    if args.vendor_root:
        vendor_root = args.vendor_root.resolve(strict=True)
        if not vendor_root.is_dir():
            raise SystemExit("--vendor-root must be a directory extracted on the host")
        expected_names = {props[k].strip('"') for k in ("goodix,firmware-name", "goodix,config-name")
                          if k in props}
        # Include driver modules for inventory only; do not load or execute them.
        expected_names |= {"goodix_core.ko", "goodix_9916r.ko", "goodix_9916.ko"}
        for path in find_named(vendor_root, expected_names):
            vendor_matches.append({"relative_path": path.relative_to(vendor_root).as_posix(),
                                   "size_bytes": path.stat().st_size,
                                   "sha256": sha256(path)})

    report = {
        "device": "POCO F5 / marble",
        "dts_source": str(dts),
        "dts_node": props,
        "required_properties_missing": missing_properties,
        "candidate_vendor_artifacts": vendor_matches,
        "vendor_root_supplied": bool(args.vendor_root),
        "upstream_source_provenance": UPSTREAM,
        "status": "inventory only; no SPI access, firmware upload, GPIO toggles, or device writes",
        "next_probe_gate": "obtain host-side matching firmware/config and confirm source protocol before any hardware probe",
    }
    rendered = json.dumps(report, indent=2) + "\n"
    if args.json_out:
        out = args.json_out.resolve()
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(rendered, encoding="utf-8")
        print(f"Wrote read-only inventory report: {out}")
    else:
        print(rendered, end="")


if __name__ == "__main__":
    main()
