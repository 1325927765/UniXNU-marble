"""Fix the bounded string matcher for the current XNU C library API."""
from pathlib import Path
import sys

p = Path(sys.argv[1]).expanduser()
s = p.read_text()
for word in ("exception", "Exception", "reason", "nil", "failed", "Failed", "Error", "container"):
    old = f'strstr(s, "{word}")'
    new = f'strnstr(s, "{word}", n)'
    if s.count(old) != 1:
        raise SystemExit(f"expected exactly one {old!r}, found {s.count(old)}")
    s = s.replace(old, new, 1)
p.write_text(s)
print(f"updated bounded matchers in {p}")
