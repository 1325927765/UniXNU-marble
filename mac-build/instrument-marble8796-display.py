"""Log first opens and selectors in the QEMU-only software framebuffer."""
from pathlib import Path
import sys

p = Path(sys.argv[1]) / 'iokit/Kernel/arm/MarbleFramebuffer.cpp'
s = p.read_text()
old = '''\tfFB->addClient(this);
\treturn true;
}

IOReturn
IOMobileFramebufferUserClient::clientClose'''
new = '''\tfFB->addClient(this);
\tIOLog("MARBLE FB: user client opened\\n");
\treturn true;
}

IOReturn
IOMobileFramebufferUserClient::clientClose'''
if s.count(old) != 1:
    raise RuntimeError('start insertion mismatch')
s = s.replace(old, new, 1)
old = '''\tuint32_t outCount = 0;

\tswitch (selector) {'''
new = '''\tuint32_t outCount = 0;
	static uint64_t seenSelectors;
	if (selector < 64 && !(seenSelectors & (1ULL << selector))) {
		seenSelectors |= 1ULL << selector;
		IOLog("MARBLE FB: first external selector %u\\n", selector);
	}

\tswitch (selector) {'''
if s.count(old) != 1:
    raise RuntimeError('selector insertion mismatch')
p.write_text(s.replace(old, new, 1))
