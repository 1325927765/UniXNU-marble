#!/usr/bin/env python3
"""Make the SwapEnd diagnostic log once without a mutable static counter."""
from datetime import datetime
from pathlib import Path


source = Path.home() / "unixnu-marble8796-build/xnu/iokit/Kernel/arm/MarbleFramebuffer.cpp"
old = source.read_text()
global_line = "static uint32_t marble_fb_swap_records_logged;\n"
start = old.find("    if (marble_fb_swap_records_logged < 16) {")
end = old.find("\n    }", start)
if old.count(global_line) != 1 or start < 0 or end < 0:
    raise SystemExit("expected diagnostic source missing; no files changed")
end += len("\n    }")
old_block = old[start:end]
if "MARBLE FB: swaprec " not in old_block or "marble_fb_swap_records_logged++" not in old_block:
    raise SystemExit("unexpected diagnostic block; no files changed")
new_block = old_block.replace("if (marble_fb_swap_records_logged < 16)", "if (!fConsolePaused)")
new_block = new_block.replace("        marble_fb_swap_records_logged++;\n", "")
updated = old.replace(global_line, "", 1).replace(old_block, new_block, 1)
backup_dir = Path.home() / "unixnu-marble8796-build/trace-backups" / datetime.now().strftime("%Y%m%d-swaptrace-fix-%H%M%S")
backup_dir.mkdir(parents=True, exist_ok=False)
(backup_dir / source.name).write_text(old)
source.write_text(updated)
print(f"patched={source}\nbackup={backup_dir / source.name}")
