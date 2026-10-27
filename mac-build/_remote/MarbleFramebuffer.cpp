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
	char trace[160];
	snprintf(trace, sizeof(trace), "open %s[%d] type=%u ret=0x%x", name, pid, type, result);
	marble_disp_note(trace);
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
	fVsync->setTimeoutUS(MARBLE_FB_VSYNC_US);

	setProperty(kIOUserClientClassKey, "IOMobileFramebufferUserClient");
	setProperty("external", false);
	setProperty("DisplayPipePlaneBaseAlignment", 64ULL, 32);
	registerService();
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

IOReturn
IOMobileFramebufferUserClient::externalMethod(uint32_t selector, IOExternalMethodArguments *args,
    __unused IOExternalMethodDispatch *dispatch, __unused OSObject *target,
    __unused void *reference)
{
	IOReturn ret = kIOReturnSuccess;
	uint64_t out[2] = { 0, 0 };
	uint32_t outCount = 0;
	static char seenNames[16][32];
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
	if (callerSlot < 16 && selector < 256 &&
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
#endif /* MARBLE */
