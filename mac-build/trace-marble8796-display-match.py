"""Record IOMobileFramebuffer matching in a QEMU-only physical ring.

The ring is written to guest physical 0x48000000 only when boot-arg
marble_disp_trace=1. That page is anonymous QEMU RAM, not a phone register.
"""
from pathlib import Path
import sys


def replace_once(text: str, old: str, new: str, label: str) -> str:
    found = text.count(old)
    if found != 1:
        raise RuntimeError(f'{label}: expected 1 match, found {found}')
    return text.replace(old, new, 1)


DISP_HELPERS = r'''
#include <IOKit/IORegistryEntry.h>
#include <IOKit/IODeviceTreeSupport.h>
#include <IOKit/IOMemoryDescriptor.h>
#include <libkern/c++/OSSerialize.h>
#include <string.h>

static int
marble_has(const char *hay, const char *needle)
{
	size_t i, j;
	if (hay == NULL || needle == NULL || needle[0] == 0) {
		return 0;
	}
	for (i = 0; hay[i] != 0; i++) {
		for (j = 0; needle[j] != 0 && hay[i + j] == needle[j]; j++) {
		}
		if (needle[j] == 0) {
			return 1;
		}
	}
	return 0;
}

/* QEMU virt scratch below the kernel and framebuffer. Not phone MMIO. */
#define MARBLE_DISP_PHYS             0x48000000ULL
#define MARBLE_DISP_SLOTS            256
#define MARBLE_DISP_LINE             224
#define MARBLE_DISP_PAGE_SIZE        65536

static char marble_disp_sticky[2200] = "census pending\n";
static char marble_disp_summary[160] = "pending";
static char marble_disp_lines[MARBLE_DISP_SLOTS][MARBLE_DISP_LINE];
static char marble_disp_snapshot[MARBLE_DISP_PAGE_SIZE - 16];
static uint32_t marble_disp_next;
static uint32_t marble_disp_filled;
static uint32_t marble_disp_seq;
static volatile UInt32 marble_disp_gate;
static char *marble_disp_page;
static IOMemoryDescriptor *marble_disp_md;
static IOMemoryMap *marble_disp_mapref;

static void
marble_disp_lock(void)
{
	while (!OSCompareAndSwap(0, 1, &marble_disp_gate)) {
	}
}

static void
marble_disp_unlock(void)
{
	__asm__ __volatile__("dmb ish" ::: "memory");
	marble_disp_gate = 0;
}

static void
marble_disp_publish(void)
{
	size_t used = 0;
	int wrote;

	if (marble_disp_page == NULL) {
		return;
	}
	marble_disp_lock();
	char *text = marble_disp_page + 16;
	size_t capacity = MARBLE_DISP_PAGE_SIZE - 16;
	wrote = snprintf(text, capacity, "%s", marble_disp_sticky);
	if (wrote > 0) {
		used = (size_t)wrote;
	}
	if (used + 5 < capacity) {
		memcpy(text + used, "---\n", 4);
		used += 4;
	}
	for (uint32_t i = 0; i < marble_disp_filled && used + 2 < capacity; i++) {
		uint32_t slot = (marble_disp_next + MARBLE_DISP_SLOTS - marble_disp_filled + i) % MARBLE_DISP_SLOTS;
		wrote = snprintf(text + used, capacity - used, "%s\n", marble_disp_lines[slot]);
		if (wrote < 0 || (size_t)wrote >= capacity - used) {
			break;
		}
		used += (size_t)wrote;
	}
	text[used] = 0;
	((uint32_t *)marble_disp_page)[2] = 1;
	((uint32_t *)marble_disp_page)[3] = (uint32_t)used;
	memcpy(marble_disp_page, "MRBLDISP", 8);
	marble_disp_unlock();
}

extern "C" void
marble_disp_note(const char *line)
{
	marble_disp_lock();
	uint32_t slot = marble_disp_next;
	snprintf(marble_disp_lines[slot], MARBLE_DISP_LINE, "%u %s", ++marble_disp_seq, line);
	marble_disp_next = (slot + 1) % MARBLE_DISP_SLOTS;
	if (marble_disp_filled < MARBLE_DISP_SLOTS) {
		marble_disp_filled++;
	}
	uint32_t seq = marble_disp_seq;
	marble_disp_unlock();
	marble_disp_publish();
	if (seq <= 256) {
		IOLog("MARBLE DISP: %s\n", line);
	}
}

static void
marble_disp_sticky_reset(void)
{
	marble_disp_lock();
	marble_disp_sticky[0] = 0;
	marble_disp_unlock();
}

static void
marble_disp_sticky_add(const char *line)
{
	marble_disp_lock();
	size_t have = strlen(marble_disp_sticky);
	size_t room = sizeof(marble_disp_sticky) - have;
	if (room >= 3) {
		int wrote = snprintf(marble_disp_sticky + have, room, "%s\n", line);
		if (wrote < 0 || (size_t)wrote >= room) {
			marble_disp_sticky[sizeof(marble_disp_sticky) - 1] = 0;
		}
	}
	marble_disp_unlock();
}

static void
marble_prop_desc(OSObject *obj, char *buf, size_t len)
{
	if (obj == NULL) {
		snprintf(buf, len, "absent");
		return;
	}
	OSBoolean *boolean = OSDynamicCast(OSBoolean, obj);
	if (boolean != NULL) {
		snprintf(buf, len, "OSBoolean:%d", boolean->isTrue() ? 1 : 0);
		return;
	}
	OSNumber *number = OSDynamicCast(OSNumber, obj);
	if (number != NULL) {
		snprintf(buf, len, "OSNumber:%llu", number->unsigned64BitValue());
		return;
	}
	OSString *string = OSDynamicCast(OSString, obj);
	if (string != NULL) {
		snprintf(buf, len, "OSString:%.40s", string->getCStringNoCopy());
		return;
	}
	OSData *data = OSDynamicCast(OSData, obj);
	if (data != NULL) {
		const uint8_t *bytes = (const uint8_t *)data->getBytesNoCopy();
		unsigned int nbyte = data->getLength();
		unsigned int i = 0;
		for (; i < nbyte; i++) {
			if (bytes[i] == 0) {
				break;
			}
			if (bytes[i] < 32 || bytes[i] > 126) {
				snprintf(buf, len, "OSData:%u", nbyte);
				return;
			}
		}
		char tmp[40];
		unsigned int copy = i < sizeof(tmp) - 1 ? i : (unsigned int)sizeof(tmp) - 1;
		memcpy(tmp, bytes, copy);
		tmp[copy] = 0;
		snprintf(buf, len, "OSData:%u:%.36s", nbyte, tmp);
		return;
	}
	snprintf(buf, len, "%s", obj->getMetaClass()->getClassName());
}

static void
marble_disp_census(const char *when)
{
	char line[180];
	char dtype[64], canvasw[48], canvash[48];
	char dfr[48], tv[48], ext[48];
	unsigned int children = 0;
	unsigned int nodes = 0;
	unsigned int services = 0;

	marble_disp_sticky_reset();
	snprintf(line, sizeof(line), "census %s", when);
	marble_disp_sticky_add(line);

	IORegistryEntry *armio = IORegistryEntry::fromPath("IODeviceTree:/arm-io", gIODTPlane);
	if (armio == NULL) {
		marble_disp_sticky_add("arm-io fromPath=none");
	} else {
		OSIterator *children_it = armio->getChildIterator(gIODTPlane);
		IORegistryEntry *child;
		if (children_it == NULL) {
			marble_disp_sticky_add("arm-io iterator=none");
		}
		while (children_it != NULL && (child = (IORegistryEntry *)children_it->getNextObject()) != NULL) {
			children++;
			marble_prop_desc(child->getProperty("device_type"), dtype, sizeof(dtype));
			if (marble_has(dtype, "display-subsystem") == 0) {
				continue;
			}
			nodes++;
			marble_prop_desc(child->getProperty("canvas-width"), canvasw, sizeof(canvasw));
			marble_prop_desc(child->getProperty("canvas-height"), canvash, sizeof(canvash));
			snprintf(line, sizeof(line), "node %s type=%s w=%s h=%s",
			    child->getName(), dtype, canvasw, canvash);
			marble_disp_sticky_add(line);
		}
		OSSafeReleaseNULL(children_it);
		armio->release();
	}
	snprintf(line, sizeof(line), "arm-io children=%u display_nodes=%u", children, nodes);
	marble_disp_sticky_add(line);

	OSDictionary *matching = IOService::serviceMatching("IOMobileFramebuffer");
	OSIterator *found = matching != NULL ? IOService::getMatchingServices(matching) : NULL;
	OSSafeReleaseNULL(matching);
	if (found == NULL) {
		marble_disp_sticky_add("service iterator=none");
	} else {
		IOService *service;
		while ((service = (IOService *)found->getNextObject()) != NULL) {
			char path[256];
			int path_len = (int)sizeof(path);
			IORegistryEntry *provider = service->getParentEntry(gIOServicePlane);
			services++;
			marble_prop_desc(service->getProperty("dfr"), dfr, sizeof(dfr));
			marble_prop_desc(service->getProperty("AppleTV"), tv, sizeof(tv));
			marble_prop_desc(service->getProperty("external"), ext, sizeof(ext));
			if (!service->getPath(path, &path_len, gIOServicePlane)) {
				strlcpy(path, "?", sizeof(path));
			}
			snprintf(line, sizeof(line), "svc %s provider=%s dfr=%s tv=%s ext=%s",
			    service->getMetaClass()->getClassName(),
			    provider != NULL ? provider->getName() : "none", dfr, tv, ext);
			marble_disp_sticky_add(line);
			snprintf(line, sizeof(line), "path %.160s", path);
			marble_disp_sticky_add(line);
		}
		found->release();
	}
	snprintf(line, sizeof(line), "service_count=%u", services);
	marble_disp_sticky_add(line);
	snprintf(marble_disp_summary, sizeof(marble_disp_summary),
	    "%s children=%u nodes=%u services=%u events=%u", when, children, nodes, services, marble_disp_seq);
	marble_disp_publish();
	IOLog("MARBLE DISP: %s\n", marble_disp_summary);
}

static void
marble_disp_map(void)
{
	int enable = 0;

	if (!PE_parse_boot_argn("marble_disp_trace", &enable, sizeof(enable)) || enable == 0) {
		IOLog("MARBLE DISP: physical trace off\n");
		return;
	}
	marble_disp_md = IOMemoryDescriptor::withPhysicalAddress(
		MARBLE_DISP_PHYS, MARBLE_DISP_PAGE_SIZE, kIODirectionInOut);
	marble_disp_mapref = marble_disp_md != NULL ? marble_disp_md->map() : NULL;
	if (marble_disp_mapref == NULL || marble_disp_mapref->getVirtualAddress() == 0) {
		IOLog("MARBLE DISP: map 0x48000000 failed\n");
		OSSafeReleaseNULL(marble_disp_mapref);
		OSSafeReleaseNULL(marble_disp_md);
		return;
	}
	marble_disp_page = (char *)marble_disp_mapref->getVirtualAddress();
	memset(marble_disp_page, 0, MARBLE_DISP_PAGE_SIZE);
	memcpy(marble_disp_page, "MRBLDISP", 8);
	IOLog("MARBLE DISP: ring at phys 0x48000000\n");
}

'''

USERCLIENT_HELPER = r'''
#if defined(ARM64_BOARD_CONFIG_MARBLE)
extern "C" void marble_disp_note(const char *line);
extern "C" void proc_selfname(char *buf, int size);

static int
marble_has(const char *hay, const char *needle)
{
	size_t i, j;
	if (hay == NULL || needle == NULL || needle[0] == 0) {
		return 0;
	}
	for (i = 0; hay[i] != 0; i++) {
		for (j = 0; needle[j] != 0 && hay[i + j] == needle[j]; j++) {
		}
		if (needle[j] == 0) {
			return 1;
		}
	}
	return 0;
}

static void
marble_disp_matching(const char *kind, OSObject *dict, unsigned int count)
{
	OSSerialize *ser = OSSerialize::withCapacity(256);
	const char *text = "";
	char name[32];
	char line[180];

	if (ser != NULL && dict != NULL && dict->serialize(ser) && ser->text() != NULL) {
		text = ser->text();
	}
	if (marble_has(text, "IOMobileFramebuffer") == 0 && marble_has(text, "display-subsystem") == 0) {
		OSSafeReleaseNULL(ser);
		return;
	}
	name[0] = 0;
	proc_selfname(name, (int)sizeof(name));
	snprintf(line, sizeof(line), "%s %s count=%u %.80s", kind, name, count, text);
	marble_disp_note(line);
	OSSafeReleaseNULL(ser);
}
#endif

'''


def patch_framebuffer(path: Path) -> None:
    text = path.read_text()
    if 'marble_disp_census' in text:
        if 'MARBLE_DISP_PAGE_SIZE' in text and 'seenByClient[16][4]' in text:
            print(f'{path.name}: persistent per-process trace already present')
            return
        upgrade = r'''static void
marble_disp_publish(void)
{
	size_t used = 0;
	int wrote;
	if (marble_disp_page == NULL) {
		return;
	}
	marble_disp_lock();
	wrote = snprintf(marble_disp_snapshot, sizeof(marble_disp_snapshot), "%s", marble_disp_sticky);
	if (wrote > 0) {
		used = (size_t)wrote;
	}
	if (used + 5 < sizeof(marble_disp_snapshot)) {
		memcpy(marble_disp_snapshot + used, "---\n", 4);
		used += 4;
	}
	for (uint32_t i = 0; i < marble_disp_filled && used + 2 < sizeof(marble_disp_snapshot); i++) {
		uint32_t slot = (marble_disp_next + MARBLE_DISP_SLOTS - marble_disp_filled + i) % MARBLE_DISP_SLOTS;
		wrote = snprintf(marble_disp_snapshot + used, sizeof(marble_disp_snapshot) - used,
		    "%s\n", marble_disp_lines[slot]);
		if (wrote < 0 || (size_t)wrote >= sizeof(marble_disp_snapshot) - used) {
			break;
		}
		used += (size_t)wrote;
	}
	volatile char *page = marble_disp_page;
	for (size_t i = 0; i < used; i++) {
		page[16 + i] = marble_disp_snapshot[i];
	}
	page[16 + used] = 0;
	page[8] = 1;
	page[9] = 0;
	page[10] = 0;
	page[11] = 0;
	page[12] = (char)(used & 0xff);
	page[13] = (char)((used >> 8) & 0xff);
	page[14] = (char)((used >> 16) & 0xff);
	page[15] = (char)((used >> 24) & 0xff);
	const char hdr[] = "MRBLDISP";
	for (size_t i = 0; i < 8; i++) {
		page[i] = hdr[i];
	}
	marble_disp_unlock();
	CleanPoC_DcacheRegion((unsigned long)marble_disp_page, 16 + used + 1);
}

'''
        start = text.index('static void\nmarble_disp_publish(void)')
        end = text.index('extern "C" void\nmarble_disp_note(', start)
        text = text[:start] + upgrade + text[end:]
        text = replace_once(text, '#define MARBLE_DISP_SLOTS            12\n',
                            '#define MARBLE_DISP_SLOTS            256\n', 'ring slots')
        text = replace_once(text, '#define MARBLE_DISP_LINE             160\n',
                            '#define MARBLE_DISP_LINE             224\n#define MARBLE_DISP_PAGE_SIZE        65536\n',
                            'ring line and page size')
        text = replace_once(text, 'static char marble_disp_lines[MARBLE_DISP_SLOTS][MARBLE_DISP_LINE];\n',
                            'static char marble_disp_lines[MARBLE_DISP_SLOTS][MARBLE_DISP_LINE];\n'
                            'static char marble_disp_snapshot[MARBLE_DISP_PAGE_SIZE - 16];\n',
                            'snapshot buffer')
        text = replace_once(text, 'if (seq <= 40) {', 'if (seq <= 256) {', 'event logging limit')
        text = replace_once(text, 'MARBLE_DISP_PHYS, 4096, kIODirectionInOut',
                            'MARBLE_DISP_PHYS, MARBLE_DISP_PAGE_SIZE, kIODirectionInOut',
                            'mapped event page')
        text = replace_once(text, 'memset(marble_disp_page, 0, 4096);',
                            'memset(marble_disp_page, 0, MARBLE_DISP_PAGE_SIZE);',
                            'cleared event page')
        text = replace_once(text,
            '    IOLog("MARBLE FB: newUserClient %s[%d] result %d handler %p\\n", name, pid, result,\n'
            '        handler != NULL ? *handler : NULL);\n',
            '    char line[160];\n'
            '    snprintf(line, sizeof(line), "open %s[%d] type=%u ret=0x%x", name, pid, type, result);\n'
            '    marble_disp_note(line);\n'
            '    IOLog("MARBLE FB: %s\\n", line);\n',
            'persistent open result')
        selector_trace = r'''	static char seenNames[16][32];
	static uint64_t seenByClient[16][4];
	char caller[32] = { 0 };
	proc_selfname(caller, sizeof(caller));
	unsigned int callerSlot = 16;
	for (unsigned int i = 0; i < 16; i++) {
		if (seenNames[i][0] == 0 || strcmp(seenNames[i], caller) == 0) {
			if (seenNames[i][0] == 0) {
				strlcpy(seenNames[i], caller, sizeof(seenNames[i]));
			}
			callerSlot = i;
			break;
		}
	}
'''
        old_selector = '''	static uint64_t seenSelectors;
	if (selector < 64 && !(seenSelectors & (1ULL << selector))) {
		seenSelectors |= 1ULL << selector;
		IOLog("MARBLE FB: first external selector %u\\n", selector);
	}
'''
        text = replace_once(text, old_selector, selector_trace, 'per-process selector tracking')
        text = replace_once(text, 'static uint64_t marble_fb_logged;        /* selectors already logged (< 64) */\n\n',
                            '', 'old selector bitset')
        old_final = '''	if (selector >= 64 || !(marble_fb_logged & (1ULL << selector))) {
		if (selector < 64) {
			marble_fb_logged |= 1ULL << selector;
		}
		char name[32];
		proc_selfname(name, sizeof(name));
		IOLog("MARBLE FB: %s sel %u in %u/%u out %u/%u -> 0x%x\\n", name, selector,
		    args->scalarInputCount, args->structureInputSize,
		    args->scalarOutputCount, args->structureOutputSize, ret);
	}
'''
        new_final = r'''	if (callerSlot < 16 && selector < 256 &&
	    !(seenByClient[callerSlot][selector / 64] & (1ULL << (selector % 64)))) {
		seenByClient[callerSlot][selector / 64] |= 1ULL << (selector % 64);
		char line[192];
		snprintf(line, sizeof(line), "selector %s sel=%u in=%u/%u out=%u/%u ret=0x%x v0=%llx v1=%llx",
		    caller, selector, args->scalarInputCount, args->structureInputSize,
		    args->scalarOutputCount, args->structureOutputSize, ret,
		    args->scalarOutputCount > 0 ? args->scalarOutput[0] : 0,
		    args->scalarOutputCount > 1 ? args->scalarOutput[1] : 0);
		marble_disp_note(line);
		IOLog("MARBLE FB: %s\n", line);
	}
'''
        text = replace_once(text, old_final, new_final, 'per-process selector results')
        path.write_text(text)
        print(f'{path.name}: upgraded to persistent per-process trace')
        return
    text = replace_once(text, '#include <kern/task.h>\n',
                        '#include <kern/task.h>\n#include <libkern/OSAtomic.h>\n',
                        'atomic include')
    text = replace_once(
        text,
        '\tvoid swap(const uint8_t *rec);\n',
        '\tvoid swap(const uint8_t *rec);\n'
        '\tIOReturn newUserClient(task_t owningTask, void *securityID, UInt32 type,\n'
        '\t    OSDictionary *properties, IOUserClient **handler) APPLE_KEXT_OVERRIDE;\n',
        'newUserClient declaration')
    implementation = r'''IOReturn
AppleCLCD::newUserClient(task_t owningTask, void *securityID, UInt32 type,
    OSDictionary *properties, IOUserClient **handler)
{
    char name[MAXCOMLEN + 1] = { 0 };
    proc_t proc = (proc_t)get_bsdtask_info(owningTask);
    int pid = proc != NULL ? proc_pid(proc) : -1;
    if (pid >= 0) {
        proc_name(pid, name, sizeof(name));
    }
    IOReturn result = IOService::newUserClient(owningTask, securityID, type, properties, handler);
    char line[160];
    snprintf(line, sizeof(line), "open %s[%d] type=%u ret=0x%x", name, pid, type, result);
    marble_disp_note(line);
    IOLog("MARBLE FB: %s\n", line);
    return result;
}

'''
    text = replace_once(text, 'bool\nAppleCLCD::start(IOService *provider)\n',
                        implementation + 'bool\nAppleCLCD::start(IOService *provider)\n',
                        'newUserClient implementation')
    text = replace_once(text, 'OSDefineMetaClassAndStructors(IOMobileFramebufferUserClient, IOUserClient);\n',
                        'OSDefineMetaClassAndStructors(IOMobileFramebufferUserClient, IOUserClient);\n' + DISP_HELPERS,
                        'helpers')
    selector_trace = r'''	static char seenNames[16][32];
	static uint64_t seenByClient[16][4];
	char caller[32] = { 0 };
	proc_selfname(caller, sizeof(caller));
	unsigned int callerSlot = 16;
	for (unsigned int i = 0; i < 16; i++) {
		if (seenNames[i][0] == 0 || strcmp(seenNames[i], caller) == 0) {
			if (seenNames[i][0] == 0) {
				strlcpy(seenNames[i], caller, sizeof(seenNames[i]));
			}
			callerSlot = i;
			break;
		}
	}
'''
    text = replace_once(text,
        '\tuint32_t outCount = 0;\n\n\tswitch (selector) {',
        '\tuint32_t outCount = 0;\n' + selector_trace + '\n\tswitch (selector) {',
        'per-process selector tracking')
    text = replace_once(text,
        '\treturn ret;\n}\n#endif /* MARBLE */',
        r'''	if (callerSlot < 16 && selector < 256 &&
	    !(seenByClient[callerSlot][selector / 64] & (1ULL << (selector % 64)))) {
		seenByClient[callerSlot][selector / 64] |= 1ULL << (selector % 64);
		char line[192];
		snprintf(line, sizeof(line), "selector %s sel=%u in=%u/%u out=%u/%u ret=0x%x v0=%llx v1=%llx",
		    caller, selector, args->scalarInputCount, args->structureInputSize,
		    args->scalarOutputCount, args->structureOutputSize, ret,
		    args->scalarOutputCount > 0 ? args->scalarOutput[0] : 0,
		    args->scalarOutputCount > 1 ? args->scalarOutput[1] : 0);
		marble_disp_note(line);
		IOLog("MARBLE FB: %s\n", line);
	}
	return ret;
}
#endif /* MARBLE */''',
        'per-process selector results')
    text = replace_once(text, '\tfVsync->setTimeoutUS(MARBLE_FB_VSYNC_US);\n',
                        '\tmarble_disp_map();\n\tfVsync->setTimeoutUS(MARBLE_FB_VSYNC_US);\n',
                        'map')
    text = replace_once(text, '\tregisterService();\n',
                        '\tmarble_disp_census("before-register");\n\tregisterService();\n'
                        '\tmarble_disp_census("after-register");\n',
                        'census')
    text = replace_once(text, '\tuint64_t count = ++fb->fVsyncCount;\n',
                        '\tuint64_t count = ++fb->fVsyncCount;\n'
                        '\tif ((count % 120) == 0) {\n'
                        '\t\tmarble_disp_census("tick");\n'
                        '\t} else if ((count % 60) == 0) {\n'
                        '\t\tmarble_disp_publish();\n'
                        '\t\tIOLog("MARBLE DISP: heartbeat %s\\n", marble_disp_summary);\n'
                        '\t}\n',
                        'heartbeat')
    path.write_text(text)
    print(f'patched {path}')


def patch_userclient(path: Path) -> None:
    text = path.read_text()
    if 'marble_disp_matching' in text:
        print(f'{path.name}: matching trace already present')
        return
    include_at = text.find('#include ')
    if include_at < 0:
        raise RuntimeError('IOUserClient.cpp has no include')
    eol = text.find('\n', include_at)
    if 'OSSerialize.h' not in text:
        text = text[:eol + 1] + '#include <libkern/c++/OSSerialize.h>\n' + text[eol + 1:]
    anchor = 'static kern_return_t\ninternal_io_service_get_matching_services('
    text = replace_once(text, anchor, USERCLIENT_HELPER + anchor, 'helper insert')
    text = replace_once(
        text,
        '\t\tIOTaskRegistryCompatibilityMatching(current_task(), dict);\n'
        '\t\t*existing = IOUserIterator::withIterator(IOService::getMatchingServices( dict ));\n',
        '\t\tIOTaskRegistryCompatibilityMatching(current_task(), dict);\n'
        '#if defined(ARM64_BOARD_CONFIG_MARBLE)\n'
        '\t\t{\n'
        '\t\t\tunsigned int count = 0;\n'
        '\t\t\tOSIterator *scan = IOService::getMatchingServices(dict);\n'
        '\t\t\tif (scan != NULL) {\n'
        '\t\t\t\twhile (scan->getNextObject() != NULL) {\n'
        '\t\t\t\t\tcount++;\n'
        '\t\t\t\t}\n'
        '\t\t\t\tscan->release();\n'
        '\t\t\t}\n'
        '\t\t\tmarble_disp_matching("services", dict, count);\n'
        '\t\t}\n'
        '#endif\n'
        '\t\t*existing = IOUserIterator::withIterator(IOService::getMatchingServices( dict ));\n',
        'services')
    text = replace_once(
        text,
        '\t\t*service = IOService::copyMatchingService( dict );\n'
        '\t\tkr = *service ? kIOReturnSuccess : kIOReturnNotFound;\n',
        '\t\t*service = IOService::copyMatchingService( dict );\n'
        '#if defined(ARM64_BOARD_CONFIG_MARBLE)\n'
        '\t\tmarble_disp_matching("service", dict, *service ? 1 : 0);\n'
        '#endif\n'
        '\t\tkr = *service ? kIOReturnSuccess : kIOReturnNotFound;\n',
        'service')
    text = replace_once(
        text,
        '\t\tnotify = IOService::addMatchingNotification( sym, dict,\n',
        '#if defined(ARM64_BOARD_CONFIG_MARBLE)\n'
        '\t\tmarble_disp_matching(notification_type, dict, 0);\n'
        '#endif\n'
        '\t\tnotify = IOService::addMatchingNotification( sym, dict,\n',
        'notify')
    text = replace_once(
        text,
        '\t*iterator = IOUserIterator::withIterator(entry->getChildIterator(\n'
        '\t\t    IORegistryEntry::getPlane( plane )));\n',
        '\t*iterator = IOUserIterator::withIterator(entry->getChildIterator(\n'
        '\t\t    IORegistryEntry::getPlane( plane )));\n'
        '#if defined(ARM64_BOARD_CONFIG_MARBLE)\n'
        '\tif (entry->getName() != NULL && strcmp(entry->getName(), "arm-io") == 0) {\n'
        '\t\tchar name[32];\n'
        '\t\tchar line[96];\n'
        '\t\tname[0] = 0;\n'
        '\t\tproc_selfname(name, (int)sizeof(name));\n'
        '\t\tsnprintf(line, sizeof(line), "children %s plane=%s", name, plane);\n'
        '\t\tmarble_disp_note(line);\n'
        '\t}\n'
        '#endif\n',
        'children')
    path.write_text(text)
    print(f'patched {path}')


def main() -> None:
    root = Path(sys.argv[1]).resolve()
    patch_framebuffer(root / 'iokit/Kernel/arm/MarbleFramebuffer.cpp')
    patch_userclient(root / 'iokit/Kernel/IOUserClient.cpp')


if __name__ == '__main__':
    main()
