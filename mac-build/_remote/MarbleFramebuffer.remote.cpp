/*
 * Built-in IOMobileFramebuffer for MARBLE: the ABL's continuous-splash
 * framebuffer (1080x2400 a8r8g8b8 in RAM, the panel scans it out by
 * itself) as the main display, driven by CoreAnimation's CPU renderer.
 *
 * IOMobileFramebuffer.framework (iOS 16.7) counts /arm-io children with
 * device_type "display-subsystem", waits for that many services matching
 * IOServiceMatching("IOMobileFramebuffer"), opens each with type 0 and
 * reads canvas-width/canvas-height from the service's provider. The class
 * here (AppleCLCD, an IOMobileFramebuffer) matches the /arm-io/disp0 nub.
 *
 * User client selectors used by CoreAnimation:
 *   3  GetLayerDefaultSurface [layer, ?] -> [IOSurface port name]
 *   4  SwapBegin -> [swap id]
 *   5  SwapEnd, struct 0x46c: +0x50 swap id, +0x54 IOSurface id per layer
 *      (4 layers), +0x64 rect a / +0xc4 rect b per layer (int x,y,w,h),
 *      +0x104 enabled layer mask
 *   6  SwapWait, 7 GetID, 8 GetDisplaySize -> [w, h], 18 IsMainDisplay,
 *   28 GetDotPitch, 72 Enable/DisableNotifications [func, refcon, type, 0]
 * Everything else is accepted and logged once.
 *
 * SwapEnd copies the enabled layers' surfaces into the panel memory (no
 * scaling, CPU copy). Vsync (notification type 5) is a 60 Hz timer that
 * sends (count, mach_absolute_time, 0) as 32-bit halves to clients that
 * enabled it, through the port they registered (IOConnectSetNotificationPort).
 *
 * The panel memory itself is published as an IOSurface and returned as the
 * default framebuffer surface. The kernel text console keeps drawing over
 * the GUI by default: pausing it (boot-arg marblefb_noconsole=1, on the
 * first swap) switches the console to serial, which also hides panics.
 */
#include "MarbleSurface.h"

#if defined(MARBLE)
#include <IOKit/IOService.h>
#include <IOKit/IOUserClient.h>
#include <IOKit/IOKitKeys.h>
#include <IOKit/IOLib.h>
#include <IOKit/IOLocks.h>
#include <IOKit/IOWorkLoop.h>
#include <IOKit/IOTimerEventSource.h>
#include <IOKit/system.h>
#include <pexpert/pexpert.h>
#include <kern/clock.h>
#include <sys/proc.h>
#include <kern/task.h>
#include <libkern/OSAtomic.h>

enum {
	kMarbleFBGetLayerDefaultSurface  = 3,
	kMarbleFBSwapBegin               = 4,
	kMarbleFBSwapEnd                 = 5,
	kMarbleFBSwapWait                = 6,
	kMarbleFBGetID                   = 7,
	kMarbleFBGetDisplaySize          = 8,
	kMarbleFBIsMainDisplay           = 18,
	kMarbleFBGetDotPitch             = 28,
	kMarbleFBNotifications           = 72,
};

#define MARBLE_FB_SWAP_REC_SIZE          0x46c
#define MARBLE_FB_LAYERS                 4
#define MARBLE_FB_NOTIFY_TYPES           8
#define MARBLE_FB_NOTIFY_VSYNC           5
#define MARBLE_FB_VSYNC_US               16667
#define MARBLE_FB_DOT_PITCH              458     /* iPhone X logical canvas */
#define MARBLE_FB_LOGICAL_W              1125
#define MARBLE_FB_LOGICAL_H              2436
#define MARBLE_FB_FORMAT_BGRA            0x42475241

class IOMobileFramebuffer : public IOService {
	OSDeclareDefaultStructors(IOMobileFramebuffer);
};

OSDefineMetaClassAndStructors(IOMobileFramebuffer, IOService);

class IOMobileFramebufferUserClient;

class AppleCLCD : public IOMobileFramebuffer {
	OSDeclareDefaultStructors(AppleCLCD);

	IOWorkLoop         *fWorkLoop;
	IOTimerEventSource *fVsync;
	uint64_t            fVsyncCount;

	static void vsyncFired(OSObject *owner, IOTimerEventSource *sender);

public:
	uint64_t      fPhys;
	uint32_t      fWidth, fHeight, fRowBytes;
	uint32_t      fLogicalW, fLogicalH;
	int32_t       fOffX, fOffY;
	uintptr_t     fPixels;          /* kernel mapping of the panel memory */
	IOMemoryMap  *fMap;
	MarbleSurface *fSurface;         /* the panel memory as an IOSurface */
	IOLock       *fLock;            /* swaps and client list */
	OSArray      *fClients;
	uint32_t      fSwapID;
	bool          fConsolePaused;

	bool start(IOService *provider) APPLE_KEXT_OVERRIDE;
	void addClient(IOMobileFramebufferUserClient *client);
	void removeClient(IOMobileFramebufferUserClient *client);
	void swap(const uint8_t *rec);
	IOReturn newUserClient(task_t owningTask, void *securityID, UInt32 type,
	    OSDictionary *properties, IOUserClient **handler) APPLE_KEXT_OVERRIDE;
};

OSDefineMetaClassAndStructors(AppleCLCD, IOMobileFramebuffer);

class IOMobileFramebufferUserClient : public IOUserClient {
	OSDeclareDefaultStructors(IOMobileFramebufferUserClient);

public:
	AppleCLCD          *fFB;
	task_t              fTask;
	mach_port_t         fPort;
	io_user_reference_t fFunc[MARBLE_FB_NOTIFY_TYPES];
	io_user_reference_t fRefcon[MARBLE_FB_NOTIFY_TYPES];

	bool initWithTask(task_t owningTask, void *securityID, UInt32 type) APPLE_KEXT_OVERRIDE;
	bool start(IOService *provider) APPLE_KEXT_OVERRIDE;
	IOReturn clientClose(void) APPLE_KEXT_OVERRIDE;
	IOReturn registerNotificationPort(mach_port_t port, UInt32 type,
	    io_user_reference_t refCon) APPLE_KEXT_OVERRIDE;
	IOReturn externalMethod(uint32_t selector, IOExternalMethodArguments *args,
	    IOExternalMethodDispatch *dispatch, OSObject *target,
	    void *reference) APPLE_KEXT_OVERRIDE;
	void notify(uint32_t type, const uint64_t *values, uint32_t count);
};

OSDefineMetaClassAndStructors(IOMobileFramebufferUserClient, IOUserClient);

#include <IOKit/IORegistryEntry.h>
#include <IOKit/IODeviceTreeSupport.h>
#include <IOKit/IOMemoryDescriptor.h>
#include <libkern/c++/OSSerialize.h>
#include <string.h>

/* QEMU virt scratch below the kernel and framebuffer. Not phone MMIO. */
#define MARBLE_DISP_PHYS             0x48000000ULL
#define MARBLE_DISP_SLOTS            12
#define MARBLE_DISP_LINE             160

static char marble_disp_sticky[2200] = "census pending\n";
static char marble_disp_summary[160] = "pending";
static char marble_disp_lines[MARBLE_DISP_SLOTS][MARBLE_DISP_LINE];
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

extern "C" void CleanPoC_DcacheRegion(unsigned long va, size_t length);

static void
marble_disp_publish(void)
{
	char local[3800];
	size_t used = 0;
	int wrote;

	if (marble_disp_page == NULL) {
		return;
	}
	marble_disp_lock();
	wrote = snprintf(local, sizeof(local), "%s", marble_disp_sticky);
	if (wrote > 0) {
		used = (size_t)wrote;
	}
	if (used + 5 < sizeof(local)) {
		memcpy(local + used, "---\n", 4);
		used += 4;
	}
	for (uint32_t i = 0; i < marble_disp_filled && used + 2 < sizeof(local); i++) {
		uint32_t slot = (marble_disp_next + MARBLE_DISP_SLOTS - marble_disp_filled + i) % MARBLE_DISP_SLOTS;
		wrote = snprintf(local + used, sizeof(local) - used, "%s\n", marble_disp_lines[slot]);
		if (wrote < 0 || (size_t)wrote >= sizeof(local) - used) {
			break;
		}
		used += (size_t)wrote;
	}
	marble_disp_unlock();
	volatile char *page = marble_disp_page;
	for (size_t i = 0; i < used; i++) {
		page[16 + i] = local[i];
	}
	page[16 + used] = 0;
	const char hdr[] = "MRBLDISP";
	for (size_t i = 0; i < 8; i++) {
		page[i] = hdr[i];
	}
	page[8] = 1;
	page[9] = 0;
	page[10] = 0;
	page[11] = 0;
	page[12] = (char)(used & 0xff);
	page[13] = (char)((used >> 8) & 0xff);
	page[14] = (char)((used >> 16) & 0xff);
	page[15] = (char)((used >> 24) & 0xff);
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
	if (seq <= 40) {
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
marble_disp_census(const char *when, IOService *self)
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

	IORegistryEntry *armio = IORegistryEntry::fromPath("IODeviceTree:/arm-io");
	if (armio == NULL) {
		marble_disp_sticky_add("arm-io IODeviceTree path=none");
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

	if (self != NULL) {
		char path[256];
		int path_len = (int)sizeof(path);
		IORegistryEntry *provider = self->getParentEntry(gIOServicePlane);
		marble_prop_desc(self->getProperty("dfr"), dfr, sizeof(dfr));
		marble_prop_desc(self->getProperty("AppleTV"), tv, sizeof(tv));
		marble_prop_desc(self->getProperty("external"), ext, sizeof(ext));
		if (!self->getPath(path, &path_len, gIOServicePlane)) {
			strlcpy(path, "?", sizeof(path));
		}
		snprintf(line, sizeof(line), "self %s provider=%s dfr=%s tv=%s ext=%s",
		    self->getMetaClass()->getClassName(),
		    provider != NULL ? provider->getName() : "none", dfr, tv, ext);
		marble_disp_sticky_add(line);
		snprintf(line, sizeof(line), "selfpath %.160s", path);
		marble_disp_sticky_add(line);
		if (provider != NULL) {
			char dtpath[256];
			int dtlen = (int)sizeof(dtpath);
			IORegistryEntry *dtparent = provider->getParentEntry(gIODTPlane);
			marble_prop_desc(provider->getProperty("device_type"), dtype, sizeof(dtype));
			if (!provider->getPath(dtpath, &dtlen, gIODTPlane)) {
				strlcpy(dtpath, "none", sizeof(dtpath));
			}
			snprintf(line, sizeof(line), "prov-dt parent=%s type=%s",
			    dtparent != NULL ? dtparent->getName() : "none", dtype);
			marble_disp_sticky_add(line);
			snprintf(line, sizeof(line), "prov-dt-path %.160s", dtpath);
			marble_disp_sticky_add(line);
		}
		IORegistryEntry *by_plane = IORegistryEntry::fromPath("arm-io", gIODTPlane);
		IORegistryEntry *by_abs = IORegistryEntry::fromPath("IODeviceTree:/arm-io", NULL);
		snprintf(line, sizeof(line), "lookup plane=%s abs=%s",
		    by_plane != NULL ? by_plane->getName() : "none",
		    by_abs != NULL ? by_abs->getName() : "none");
		marble_disp_sticky_add(line);
		OSSafeReleaseNULL(by_plane);
		OSSafeReleaseNULL(by_abs);
	}
	OSDictionary *matching = IOService::serviceMatching("IOMobileFramebuffer");
	if (matching == NULL) {
		marble_disp_sticky_add("matching_dict=none");
	} else {
	OSIterator *found = IOService::getMatchingServices(matching);
	matching->release();
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
	}
	snprintf(line, sizeof(line), "services=%u", services);
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
	    MARBLE_DISP_PHYS, 4096, kIODirectionInOut);
	marble_disp_mapref = marble_disp_md != NULL ? marble_disp_md->map() : NULL;
	if (marble_disp_mapref == NULL || marble_disp_mapref->getVirtualAddress() == 0) {
		IOLog("MARBLE DISP: map 0x48000000 failed\n");
		OSSafeReleaseNULL(marble_disp_mapref);
		OSSafeReleaseNULL(marble_disp_md);
		return;
	}
	marble_disp_page = (char *)marble_disp_mapref->getVirtualAddress();
	memset(marble_disp_page, 0, 4096);
	memcpy(marble_disp_page, "MRBLDISP", 8);
	IOLog("MARBLE DISP: ring at phys 0x48000000\n");
}


IOReturn
AppleCLCD::newUserClient(task_t owningTask, void *securityID, UInt32 type,
    OSDictionary *properties, IOUserClient **handler)
{
    char name[MAXCOMLEN + 1] = { 0 };
    proc_t proc = (proc_t)get_bsdtask_info(owningTask);
    int pid = proc != NULL ? proc_pid(proc) : -1;
    if (pid >= 0) {
        proc_name(pid, name, sizeof(name));
    }
    IOLog("MARBLE FB: newUserClient %s[%d] request type %u\n", name, pid, type);
    IOReturn result = IOService::newUserClient(owningTask, securityID, type, properties, handler);
    IOLog("MARBLE FB: newUserClient %s[%d] result %d handler %p\n", name, pid, result,
        handler != NULL ? *handler : NULL);
    return result;
}

bool
AppleCLCD::start(IOService *provider)
{
	PE_Video video;

	if (!IOService::start(provider)) {
		return false;
	}
	PE_current_console(&video);
	fPhys = video.v_baseAddr;
	fWidth = (uint32_t)video.v_width;
	fHeight = (uint32_t)video.v_height;
	fRowBytes = (uint32_t)video.v_rowBytes;
	int native = 0;
	PE_parse_boot_argn("marblefb_native", &native, sizeof(native));
	fLogicalW = fWidth;
	fLogicalH = fHeight;
	if (!native && fWidth <= MARBLE_FB_LOGICAL_W && fHeight <= MARBLE_FB_LOGICAL_H) {
		fLogicalW = MARBLE_FB_LOGICAL_W;
		fLogicalH = MARBLE_FB_LOGICAL_H;
	}
	fOffX = (int32_t)(fLogicalW - fWidth) / 2;
	fOffY = (int32_t)(fLogicalH - fHeight) / 2;
	if (fPhys == 0 || fWidth == 0 || fHeight == 0 || fRowBytes < fWidth * 4) {
		IOLog("MARBLE FB: no boot framebuffer\n");
		return false;
	}
	fLock = IOLockAlloc();
	fClients = OSArray::withCapacity(4);
	fSurface = marble_surface_create_physical(fPhys, fWidth, fHeight, fRowBytes, MARBLE_FB_FORMAT_BGRA);
	fPixels = fSurface != NULL ? fSurface->kernelAddress() : 0;
	fWorkLoop = IOWorkLoop::workLoop();
	if (fLock == NULL || fClients == NULL || fPixels == 0 || fWorkLoop == NULL) {
		IOLog("MARBLE FB: setup failed\n");
		OSSafeReleaseNULL(fSurface);    /* stays published: also held by the table */
		OSSafeReleaseNULL(fWorkLoop);
		return false;
	}
	fVsync = IOTimerEventSource::timerEventSource(this, &AppleCLCD::vsyncFired);
	if (fVsync == NULL || fWorkLoop->addEventSource(fVsync) != kIOReturnSuccess) {
		IOLog("MARBLE FB: no vsync timer\n");
		return false;
	}
	marble_disp_map();
	fVsync->setTimeoutUS(MARBLE_FB_VSYNC_US);

	setProperty(kIOUserClientClassKey, "IOMobileFramebufferUserClient");
	setProperty("external", false);
	setProperty("DisplayPipePlaneBaseAlignment", 64ULL, 32);
	marble_disp_census("before-register", this);
	registerService();
	marble_disp_census("after-register", this);
	IOLog("MARBLE FB: AppleCLCD %ux%u stride %u at 0x%llx, default surface %u, presented as %ux%u\n",
	    fWidth, fHeight, fRowBytes, fPhys, fSurface->id, fLogicalW, fLogicalH);
	return true;
}

void
AppleCLCD::vsyncFired(OSObject *owner, IOTimerEventSource *sender)
{
	AppleCLCD *fb = (AppleCLCD *)owner;
	uint64_t now = mach_absolute_time();
	uint64_t count = ++fb->fVsyncCount;
	if ((count % 120) == 0) {
		marble_disp_census("tick", fb);
	} else if ((count % 60) == 0) {
		marble_disp_publish();
		IOLog("MARBLE DISP: heartbeat %s\n", marble_disp_summary);
	}
	uint64_t values[6] = {
		(uint32_t)count, (uint32_t)(count >> 32),
		(uint32_t)now, (uint32_t)(now >> 32),
		0, 0,
	};

	IOLockLock(fb->fLock);
	for (unsigned int i = 0; i < fb->fClients->getCount(); i++) {
		IOMobileFramebufferUserClient *client =
		    (IOMobileFramebufferUserClient *)fb->fClients->getObject(i);
		client->notify(MARBLE_FB_NOTIFY_VSYNC, values, 6);
	}
	IOLockUnlock(fb->fLock);
	sender->setTimeoutUS(MARBLE_FB_VSYNC_US);
}

void
AppleCLCD::addClient(IOMobileFramebufferUserClient *client)
{
	IOLockLock(fLock);
	fClients->setObject(client);
	IOLockUnlock(fLock);
}

void
AppleCLCD::removeClient(IOMobileFramebufferUserClient *client)
{
	IOLockLock(fLock);
	unsigned int i = fClients->getNextIndexOfObject(client, 0);
	if (i != (unsigned int)-1) {
		fClients->removeObject(i);
	}
	IOLockUnlock(fLock);
}

static uint32_t
get32(const uint8_t *p, uint32_t off)
{
	uint32_t v;
	memcpy(&v, p + off, 4);
	return v;
}

static uint32_t marble_fb_swaps_logged;

/* Copy each enabled layer's surface into the panel memory (no scaling). */
void
AppleCLCD::swap(const uint8_t *rec)
{
	uint32_t mask = get32(rec, 0x104);

	if (!fConsolePaused) {
		int quiet = 0;
		fConsolePaused = true;
		if (PE_parse_boot_argn("marblefb_noconsole", &quiet, sizeof(quiet)) && quiet != 0) {
			PE_Video video;
			PE_current_console(&video);
			PE_initialize_console(&video, kPEDisableScreen);
		}
	}

	for (uint32_t layer = 0; layer < MARBLE_FB_LAYERS; layer++) {
		uint32_t id = get32(rec, 0x54 + 4 * layer);
		const uint8_t *a = rec + 0x64 + 16 * layer;
		const uint8_t *b = rec + 0xc4 + 16 * layer;
		int32_t sx = (int32_t)get32(a, 0), sy = (int32_t)get32(a, 4);
		int32_t dx = (int32_t)get32(b, 0), dy = (int32_t)get32(b, 4);
		int32_t w = (int32_t)get32(b, 8), h = (int32_t)get32(b, 12);

		if (!(mask & (1u << layer)) || id == 0) {
			continue;
		}
		MarbleSurface *s = marble_surface_copy(id);
		if (marble_fb_swaps_logged < 16) {
			marble_fb_swaps_logged++;
			IOLog("MARBLE FB: swap %u layer %u surface %u %ux%u fmt 0x%x bpr %u a %d,%d %ux%u b %d,%d %dx%d\n",
			    get32(rec, 0x50), layer, id, s ? s->width : 0, s ? s->height : 0,
			    s ? s->pixelFormat : 0, s ? s->bytesPerRow : 0, sx, sy, get32(a, 8),
			    get32(a, 12), dx, dy, w, h);
		}
		if (s == NULL || s == fSurface) {
			OSSafeReleaseNULL(s);
			continue;
		}
		uintptr_t src = s->kernelAddress();
		uint32_t bpe = s->bytesPerElement ? s->bytesPerElement : 4;
		if (w <= 0 || h <= 0) {
			w = (int32_t)s->width;
			h = (int32_t)s->height;
		}
		if (sx < 0 || sy < 0) {
			sx = sy = 0;
		}
		if (dx < 0 || dy < 0) {
			dx = dy = 0;
		}
		dx -= fOffX;
		dy -= fOffY;
		if (dx < 0) { sx -= dx; w += dx; dx = 0; }
		if (dy < 0) { sy -= dy; h += dy; dy = 0; }
		if (w > (int32_t)s->width - sx) {
			w = (int32_t)s->width - sx;
		}
		if (h > (int32_t)s->height - sy) {
			h = (int32_t)s->height - sy;
		}
		if (w > (int32_t)fWidth - dx) {
			w = (int32_t)fWidth - dx;
		}
		if (h > (int32_t)fHeight - dy) {
			h = (int32_t)fHeight - dy;
		}
		uint64_t last = (uint64_t)s->offset + (uint64_t)(sy + h - 1) * s->bytesPerRow +
		    (uint64_t)(sx + w) * 4;
		if (w <= 0 || h <= 0 || s->elementWidth != 1 || s->elementHeight != 1 ||
		    s->memory == NULL || last > s->memory->getLength()) {
			src = 0;
		}
		if (src != 0 && bpe == 4) {
			for (int32_t y = 0; y < h; y++) {
				memcpy((void *)(fPixels + (uint64_t)(dy + y) * fRowBytes + (uint64_t)dx * 4),
				    (const void *)(src + s->offset + (uint64_t)(sy + y) * s->bytesPerRow + (uint64_t)sx * 4),
				    (size_t)w * 4);
			}
		}
		s->release();
	}
}

bool
IOMobileFramebufferUserClient::initWithTask(task_t owningTask, void *securityID, UInt32 type)
{
	if (!IOUserClient::initWithTask(owningTask, securityID, type)) {
		return false;
	}
	fTask = owningTask;
	return true;
}

bool
IOMobileFramebufferUserClient::start(IOService *provider)
{
	fFB = OSDynamicCast(AppleCLCD, provider);
	if (fFB == NULL || !IOUserClient::start(provider)) {
		return false;
	}
	fFB->addClient(this);
	IOLog("MARBLE FB: user client opened\n");
	return true;
}

IOReturn
IOMobileFramebufferUserClient::clientClose(void)
{
	if (fFB != NULL) {
		fFB->removeClient(this);
		IOLockLock(fFB->fLock);
		mach_port_t old = fPort;
		fPort = MACH_PORT_NULL;
		IOLockUnlock(fFB->fLock);
		if (old != MACH_PORT_NULL) {
			releaseNotificationPort(old);
		}
	}
	terminate();
	return kIOReturnSuccess;
}

IOReturn
IOMobileFramebufferUserClient::registerNotificationPort(mach_port_t port, __unused UInt32 type,
    __unused io_user_reference_t refCon)
{
	mach_port_t old;
	IOLockLock(fFB->fLock);
	old = fPort;
	fPort = port;
	IOLockUnlock(fFB->fLock);
	if (old != MACH_PORT_NULL) {
		releaseNotificationPort(old);
	}
	return kIOReturnSuccess;
}

/* Called with the framebuffer lock held. */
void
IOMobileFramebufferUserClient::notify(uint32_t type, const uint64_t *values, uint32_t count)
{
	OSAsyncReference64 ref;

	if (type >= MARBLE_FB_NOTIFY_TYPES || fFunc[type] == 0 || fPort == MACH_PORT_NULL) {
		return;
	}
	bzero(ref, sizeof(ref));
	setAsyncReference64(ref, fPort, (mach_vm_address_t)fFunc[type], fRefcon[type], fTask);
	sendAsyncResult64WithOptions(ref, kIOReturnSuccess, (io_user_reference_t *)values, count,
	    kIOUserNotifyOptionCanDrop);
}

static uint64_t marble_fb_logged;        /* selectors already logged (< 64) */

IOReturn
IOMobileFramebufferUserClient::externalMethod(uint32_t selector, IOExternalMethodArguments *args,
    __unused IOExternalMethodDispatch *dispatch, __unused OSObject *target,
    __unused void *reference)
{
	IOReturn ret = kIOReturnSuccess;
	uint64_t out[2] = { 0, 0 };
	uint32_t outCount = 0;
	static uint64_t seenSelectors;
	if (selector < 64 && !(seenSelectors & (1ULL << selector))) {
		seenSelectors |= 1ULL << selector;
		IOLog("MARBLE FB: first external selector %u\n", selector);
	}

	switch (selector) {
	case kMarbleFBGetLayerDefaultSurface:
		out[0] = marble_surface_port_in_task(fFB->fSurface, fTask);
		outCount = 1;
		break;
	case kMarbleFBSwapBegin:
		IOLockLock(fFB->fLock);
		out[0] = ++fFB->fSwapID;
		IOLockUnlock(fFB->fLock);
		outCount = 1;
		break;
	case kMarbleFBSwapEnd: {
		uint8_t rec[MARBLE_FB_SWAP_REC_SIZE];
		if (args->structureInputDescriptor != NULL ||
		    args->structureInputSize < MARBLE_FB_SWAP_REC_SIZE) {
			ret = kIOReturnBadArgument;
			break;
		}
		memcpy(rec, args->structureInput, sizeof(rec));
		fFB->swap(rec);
		break;
	}
	case kMarbleFBGetID:
		out[0] = 0;
		outCount = 1;
		break;
	case kMarbleFBGetDisplaySize:
		out[0] = fFB->fLogicalW;
		out[1] = fFB->fLogicalH;
		outCount = 2;
		break;
	case kMarbleFBIsMainDisplay:
		out[0] = 1;
		outCount = 1;
		break;
	case kMarbleFBGetDotPitch:
		out[0] = MARBLE_FB_DOT_PITCH;
		outCount = 1;
		break;
	case kMarbleFBNotifications:
		if (args->scalarInputCount >= 3 && args->scalarInput[2] < MARBLE_FB_NOTIFY_TYPES) {
			uint32_t type = (uint32_t)args->scalarInput[2];
			IOLockLock(fFB->fLock);
			fFunc[type] = args->scalarInput[0];
			fRefcon[type] = args->scalarInput[1];
			IOLockUnlock(fFB->fLock);
			char name[32];
			proc_selfname(name, sizeof(name));
			IOLog("MARBLE FB: %s notifications type %u %s\n", name, type,
			    args->scalarInput[0] ? "on" : "off");
		}
		break;
	case kMarbleFBSwapWait:
	default:
		break;
	}

	for (uint32_t i = 0; i < args->scalarOutputCount; i++) {
		args->scalarOutput[i] = i < outCount ? out[i] : 0;
	}
	if (args->structureOutputDescriptor == NULL && args->structureOutput != NULL) {
		bzero(args->structureOutput, args->structureOutputSize);
	}
	if (selector >= 64 || !(marble_fb_logged & (1ULL << selector))) {
		if (selector < 64) {
			marble_fb_logged |= 1ULL << selector;
		}
		char name[32];
		proc_selfname(name, sizeof(name));
		IOLog("MARBLE FB: %s sel %u in %u/%u out %u/%u -> 0x%x\n", name, selector,
		    args->scalarInputCount, args->structureInputSize,
		    args->scalarOutputCount, args->structureOutputSize, ret);
	}
	return ret;
}
#endif /* MARBLE */
