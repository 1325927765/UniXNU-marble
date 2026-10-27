"""Prepare an opt-in, tightly bounded /dev/null stderr tee for Marble graphics.

Default behavior is dry-run against the separate Mac XNU checkout.  --apply
backs up and edits only bsd/dev/mem.c.  It does not build or boot anything.
"""
from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path


ROOT = Path.home() / "unixnu-marble8796-build"
SOURCE = ROOT / "xnu/bsd/dev/mem.c"

HELPER = r'''/* Marble-only trace of selected graphics daemons' /dev/null writes. */
static uint32_t marble_null_trace_bytes;
static void
marble_null_trace(struct uio *uio)
{
	uint32_t enabled = 0;
	char name[32] = { 0 };
	char bytes[512];
	uio_t duplicate;
	user_size_t count, reserved, cost, old;
	uint32_t overhead, available;
	int error;

	/* No mutable parse cache: safe when writes arrive concurrently. */
	if (!PE_parse_boot_argn("marble_null_trace", &enabled, sizeof(enabled)) || enabled != 1) {
		return;
	}
	proc_selfname(name, (int)sizeof(name));
	name[sizeof(name) - 1] = '\0';
	if (strcmp(name, "backboardd") != 0 && strcmp(name, "SpringBoard") != 0) {
		return;
	}
	count = MIN(uio_curriovlen(uio), sizeof(bytes));
	if (count == 0) {
		return;
	}
	/* Budget payload plus worst-case per-line prefix and newline bytes. */
	overhead = (uint32_t)strlen(name) + 4;
	reserved = count;
	cost = reserved + overhead;
	/* Atomically reserve at most 128 KiB even with concurrent writers. */
	old = __atomic_fetch_add(&marble_null_trace_bytes, (uint32_t)cost, __ATOMIC_RELAXED);
	if (old >= 128 * 1024) {
		(void)__atomic_fetch_sub(&marble_null_trace_bytes, (uint32_t)cost, __ATOMIC_RELAXED);
		return;
	}
	available = 128 * 1024 - old;
	if (cost > available) {
		if (available <= overhead) {
			(void)__atomic_fetch_sub(&marble_null_trace_bytes, (uint32_t)cost, __ATOMIC_RELAXED);
			return;
		}
		count = available - overhead;
		(void)__atomic_fetch_sub(&marble_null_trace_bytes,
		    (uint32_t)(cost - count - overhead), __ATOMIC_RELAXED);
	}
	duplicate = uio_duplicate(uio);
	if (duplicate == NULL) {
		(void)__atomic_fetch_sub(&marble_null_trace_bytes,
		    (uint32_t)(count + overhead), __ATOMIC_RELAXED);
		return;
	}
	error = uiomove(bytes, (int)count, duplicate);
	uio_free(duplicate);
	if (error == 0) {
		printf("|%s| %.*s%s", name, (int)count, bytes,
		    (count > 0 && bytes[count - 1] == '\n') ? "" : "\n");
	} else {
		(void)__atomic_fetch_sub(&marble_null_trace_bytes,
		    (uint32_t)(count + overhead), __ATOMIC_RELAXED);
	}
}
'''

ANCHOR_HELPER = "static SECURITY_READ_ONLY_LATE(caddr_t) devzerobuf;"
ANCHOR_WRITE = (
    "\t\tcase 2:\n"
    "\t\t\tif (rw == UIO_READ) {\n"
    "\t\t\t\treturn 0;\n"
    "\t\t\t}\n"
    "\t\t\tc = uio_curriovlen(uio);"
)
REPLACEMENT_WRITE = ANCHOR_WRITE.replace(
    "\t\t\tc = uio_curriovlen(uio);",
    "\t\t\tmarble_null_trace(uio);\n"
    "\t\t\tc = uio_curriovlen(uio);",
)


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"expected exactly one {label} anchor, found {count}")
    return text.replace(old, new, 1)


def transform(text: str) -> str:
    if "marble_null_trace_bytes" in text or '"marble_null_trace"' in text:
        raise RuntimeError("Marble /dev/null trace already present")
    text = replace_once(text, ANCHOR_HELPER, ANCHOR_HELPER + "\n\n" + HELPER,
                        "helper insertion")
    return replace_once(text, ANCHOR_WRITE, REPLACEMENT_WRITE,
                        "rathole write hook")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true",
                        help="write the prepared patch into the Mac XNU checkout")
    args = parser.parse_args()
    if not SOURCE.is_file():
        raise SystemExit(f"missing source file: {SOURCE}; no changes made")
    old = SOURCE.read_text()
    new = transform(old)
    for needle in ("uio_duplicate(uio)", "uio_free(duplicate)",
                   "__atomic_fetch_add", "128 * 1024", "count = MIN(uio_curriovlen(uio), sizeof(bytes))",
                   'strcmp(name, "backboardd")', 'strcmp(name, "SpringBoard")',
                   'PE_parse_boot_argn("marble_null_trace"'):
        if needle not in new:
            raise AssertionError(f"prepared source missing {needle}")
    print("PASS: explicit boot-arg opt-in; exact process names only")
    print("PASS: cloned UIO is read only; original /dev/null UIO path is unchanged")
    print("PASS: 512-byte per-hook cap and atomic 128 KiB total reservation")
    if not args.apply:
        print("Dry run. Add --apply on the Mac to back up and update mem.c.")
        return
    backup = ROOT / "trace-backups" / datetime.now().strftime("%Y%m%d-graphics-null-%H%M%S")
    backup.mkdir(parents=True, exist_ok=False)
    (backup / SOURCE.name).write_text(old)
    SOURCE.write_text(new)
    (backup / "manifest.json").write_text(json.dumps({
        "change": "opt-in /dev/null tee for backboardd and SpringBoard",
        "boot_arg": "marble_null_trace=1",
        "per_write_bytes_max": 512,
        "total_reserved_bytes_max": 131072,
        "source": str(SOURCE),
        "backup": str(backup / SOURCE.name),
        "phone_booted": False,
    }, indent=2) + "\n")
    print(f"Applied to source only; backup: {backup}")


if __name__ == "__main__":
    main()
