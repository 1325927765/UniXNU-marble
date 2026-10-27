#!/usr/bin/env python3
"""Temporarily allow a QEMU MARBLE kernel to stop writing the video console.

Apple's ARM console selector is read-only after boot. This test-only source
change keeps it writable so `marblefb_noconsole=1` can switch the console.
Restore the printed backup before building a phone kernel.
"""
from datetime import datetime
from pathlib import Path


source = Path.home() / "unixnu-marble8796-build/xnu/osfmk/console/serial_console.c"
old = source.read_text()
anchor = "#if __x86_64__\nuint32_t cons_ops_index = VC_CONS_OPS;\n#else\nSECURITY_READ_ONLY_LATE(uint32_t) cons_ops_index = VC_CONS_OPS;\n#endif"
if old.count(anchor) != 1:
    raise SystemExit("console selector source differs; no files changed")
replacement = anchor.replace("#if __x86_64__", "#if __x86_64__ || defined(MARBLE)")
backup_dir = Path.home() / "unixnu-marble8796-build/trace-backups" / datetime.now().strftime("%Y%m%d-console-switch-%H%M%S")
backup_dir.mkdir(parents=True, exist_ok=False)
(backup_dir / source.name).write_text(old)
source.write_text(old.replace(anchor, replacement, 1))
print(f"patched={source}\nbackup={backup_dir / source.name}")
