#!/usr/bin/env python3
"""Log the first 16 AppleCLCD SwapEnd layer masks and surface IDs.

Run on the Mac source tree. This is diagnostic only and keeps a source backup.
"""
from datetime import datetime
from pathlib import Path


root = Path.home() / "unixnu-marble8796-build/xnu"
source = root / "iokit/Kernel/arm/MarbleFramebuffer.cpp"
old = source.read_text()
marker = "MARBLE FB: swaprec "
if marker in old:
    print("swap trace already installed")
    raise SystemExit(0)

global_anchor = "static uint32_t marble_fb_swaps_logged;"
swap_anchor = "uint32_t mask = get32(rec, 0x104);"
if old.count(global_anchor) != 1 or old.count(swap_anchor) != 1:
    raise SystemExit("AppleCLCD::swap source differs; no files changed")
swap_trace = """
    if (marble_fb_swap_records_logged < 16) {
        marble_fb_swap_records_logged++;
        IOLog("MARBLE FB: swaprec id=%u mask=0x%x surfaces=%u,%u,%u,%u\\n",
            get32(rec, 0x50), mask, get32(rec, 0x54), get32(rec, 0x58),
            get32(rec, 0x5c), get32(rec, 0x60));
    }
"""
backup_dir = Path.home() / "unixnu-marble8796-build/trace-backups" / datetime.now().strftime("%Y%m%d-swaptrace-%H%M%S")
backup_dir.mkdir(parents=True, exist_ok=False)
backup = backup_dir / "MarbleFramebuffer.cpp"
backup.write_text(old)
updated = old.replace(global_anchor, global_anchor + "\nstatic uint32_t marble_fb_swap_records_logged;", 1)
updated = updated.replace(swap_anchor, swap_anchor + swap_trace, 1)
source.write_text(updated)
print(f"patched={source}\nbackup={backup}")
