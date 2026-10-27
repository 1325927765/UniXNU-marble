"""Extend the existing Marble heap scanner to watchdogd's intentional SIGTRAP."""
from pathlib import Path
import sys

path = Path(sys.argv[1]).expanduser().resolve()
text = path.read_text()
old = '\tif (sig == 6 && strcmp(name, "backboardd") == 0) {\n'
new = ('\tif ((sig == 6 && strcmp(name, "backboardd") == 0) ||\n'
       '\t    (sig == 5 && strcmp(name, "watchdogd") == 0)) {\n')
assert text.count(old) == 1, "expected existing gated crash scanner"
text = text.replace(old, new, 1)
old_filter = ('\t\t\t\t\t    strnstr(s, "Failed", n) || strnstr(s, "Error", n) || '
              'strnstr(s, "container", n)) {\n')
new_filter = ('\t\t\t\t\t    strnstr(s, "Failed", n) || strnstr(s, "Error", n) ||\n'
              '\t\t\t\t\t    strnstr(s, "container", n) || strnstr(s, "watchdog", n) ||\n'
              '\t\t\t\t\t    strnstr(s, "IOService", n) || strnstr(s, "kext", n) ||\n'
              '\t\t\t\t\t    strnstr(s, "discover", n) || strnstr(s, "open", n)) {\n')
assert text.count(old_filter) == 1, "expected old scanner filter"
path.write_text(text.replace(old_filter, new_filter, 1))
print("extended Marble crash scanner for watchdogd")
