"""Retire reference-board physical framebuffer writes before phone qualification.

The ordinary ADT-configured framebuffer serial console remains available.
No framebuffer mapping or write may occur before that validated setup.
"""
from pathlib import Path
import re
import json
import hashlib

r = Path.home()/'unixnu-marble8796-build'
src = r/'xnu'
changed = []
p = src/'osfmk/arm64/start.s'
text = p.read_text()
blocks = re.findall(r'#if defined\(MARBLE\)\n.*?#endif',text,re.S)
targets = [b for b in blocks if '0x9c000000' in b]
assert len(targets) == 2
for block in targets:
    text = text.replace(block,'/* Reference-board early framebuffer access retired. */',1)
assert '0x9c000000' not in text
p.write_text(text)
changed.append(str(p.relative_to(src)))
p = src/'osfmk/arm64/arm_vm_init.c'
text = p.read_text()
pattern = r'#if defined\(MARBLE\)\n/\*\n \* The reserved low-globals/kernel region.*?\n#endif'
text, count = re.subn(pattern,'/* Early framebuffer alias retired; serial uses the ADT mapping. */',text,count=1,flags=re.S)
assert count == 1
text = text.replace('marble_early_map_final();','/* No reference framebuffer mapping. */')
text = text.replace('marble_early_relocate(MARBLE_EARLY_FB_VA);','/* No reference framebuffer relocation. */')
assert '0x9c000000' not in text and 'MARBLE_EARLY_FB_VA' not in text
p.write_text(text)
changed.append(str(p.relative_to(src)))
p = src/'osfmk/arm64/marble_early.c'
assert '0x9c000000' in p.read_text()
p.write_text('''/* No physical framebuffer writes before the ADT serial console is configured. */
#include <arm64/marble_early.h>
#if defined(MARBLE)
void marble_early_mark(unsigned int stage, const char *label) { (void)stage; (void)label; }
void marble_early_putc(char c) { (void)c; }
void marble_early_panic(const char *fmt, va_list *args) { (void)fmt; (void)args; }
void marble_early_relocate(uint64_t base) { (void)base; }
void marble_early_disable(void) {}
#endif
''')
changed.append(str(p.relative_to(src)))
report = dict(reason='reference fixed physical framebuffer does not belong to marble',
              replacement='ordinary ADT-configured ml_io_map_wcomb serial framebuffer only',
              early_panic_screen_available=False,
              files={name:hashlib.sha256((src/name).read_bytes()).hexdigest() for name in changed},
              phone_boot_qualified=False)
(r/'reference-framebuffer-retired.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report,indent=2))
