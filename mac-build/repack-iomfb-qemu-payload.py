"""Repack the caller-trace Mach-O with the prior iOS QEMU ADT and boot args."""
from pathlib import Path
import struct
import subprocess

root = Path.home() / 'rom-lab/unixnu-marble'
lab = Path(__file__).resolve().parents[1]
research = lab / 'research/marble8796-20261024'
old = (root / 'research/marble8796-20261024/qemu-ios-iomfb-open.bin').read_bytes()
adt_off, adt_size = struct.unpack_from('<QQ', old, 0x20)
adt_path = research / 'qemu-ios-iomfb-caller-trace.adt'
adt_path.write_bytes(old[adt_off:adt_off + adt_size])
cmdline = old[0x48:0x48 + 608].split(b'\0', 1)[0].decode()
payload = research / 'qemu-ios-iomfb-caller-trace.bin'
builder = lab / 'research/reference-ios-sweet/tools/mkpayload.py'
kernel = research / 'iomfb-caller-trace.macho'
subprocess.run(['python3', str(builder), str(kernel), str(adt_path), str(payload),
                '--cmdline', cmdline], check=True)
