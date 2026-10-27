/*
 * Boot-argument-gated Marble GENI clock/register snapshot. Mode 2 makes one
 * temporary, guarded S4 clock-vote RMW; this is not an SPI/touch driver.
 */
#include <pexpert/arm64/board_config.h>

#if defined(ARM64_BOARD_CONFIG_MARBLE)
#include <pexpert/pexpert.h>
#include <IOKit/IOService.h>
#include <IOKit/IOLib.h>
#include <IOKit/IOMemoryDescriptor.h>
#include <IOKit/IOMapTypes.h>
#include <libkern/OSAtomic.h>
#include "MarbleTouchProbeClock.h"
#include "MarbleTouchPrereq.h"

class MarbleTouchProbe : public IOService {
	OSDeclareDefaultStructors(MarbleTouchProbe);

public:
	bool start(IOService *provider) APPLE_KEXT_OVERRIDE;
};

OSDefineMetaClassAndStructors(MarbleTouchProbe, IOService);

namespace {
static const uint64_t kGccPhysical = 0x00100000ULL;
static const uint64_t kGccLength = 0x00063000ULL; /* includes GCC offset 0x62008 */
static const uint64_t kSePhysical = 0x00990000ULL;
static const uint64_t kSeLength = 0x00004000ULL;
static const uint64_t kWrapperPhysical = 0x009c0000ULL;
static const uint64_t kWrapperLength = 0x00002000ULL;

static const uint32_t kClockOff = 1u << 31;
static const uint32_t kSourceClockOn = 1u << 14;
static const uint32_t kMasterAhbOn = 1u << 6;
static const uint32_t kSlaveAhbOn = 1u << 7;
static volatile UInt32 gMarbleTouchClockProbeState = 0; /* 0=unused, 1=running, 2=consumed */

static uint32_t
readReg(const volatile uint32_t *base, uint32_t offset)
{
	return base[offset / sizeof(uint32_t)];
}

static IOMemoryMap *
mapReadOnly(uint64_t physical, uint64_t length, IOMemoryDescriptor **descriptor)
{
	*descriptor = IOMemoryDescriptor::withPhysicalAddress(
	    physical, length, kIODirectionIn);
	if (*descriptor == NULL) {
		return NULL;
	}
	return (*descriptor)->map(kIOMapInhibitCache | kIOMapReadOnly);
}

static bool
takeSeSnapshot(void)
{
	/* GENI read-info snapshot only; deliberately no controller initialization. */
	IOMemoryDescriptor *seDescriptor = NULL;
	IOMemoryMap *seMap = mapReadOnly(kSePhysical, kSeLength, &seDescriptor);
	if (seMap == NULL || seMap->getVirtualAddress() == 0) {
		IOLog("MARBLE TOUCH PROBE: SE read-only map failed\n");
		if (seMap != NULL) seMap->release();
		if (seDescriptor != NULL) seDescriptor->release();
		return false;
	}
	const volatile uint32_t *se = (const volatile uint32_t *)seMap->getVirtualAddress();
	const uint32_t firmware = readReg(se, 0x068);
	const uint32_t ifDisable = readReg(se, 0x064);
	const uint32_t status = readReg(se, 0x040);
	const uint32_t hardware = readReg(se, 0xe24);
	seMap->release();
	seDescriptor->release();

	IOMemoryDescriptor *wrapperDescriptor = NULL;
	IOMemoryMap *wrapperMap = mapReadOnly(kWrapperPhysical, kWrapperLength,
	    &wrapperDescriptor);
	if (wrapperMap == NULL || wrapperMap->getVirtualAddress() == 0) {
		IOLog("MARBLE TOUCH PROBE: wrapper read-only map failed; QUP version unavailable\n");
		if (wrapperMap != NULL) wrapperMap->release();
		if (wrapperDescriptor != NULL) wrapperDescriptor->release();
		return false;
	}
	const volatile uint32_t *wrapper =
	    (const volatile uint32_t *)wrapperMap->getVirtualAddress();
	const uint32_t qupVersion = readReg(wrapper, 0x004);
	wrapperMap->release();
	wrapperDescriptor->release();

	IOLog("MARBLE TOUCH PROBE: SE fw=0x%08x proto=%u if_disable=0x%08x status=0x%08x hw=0x%08x qup=0x%08x fifo_disabled=%u\n",
	    firmware, (firmware >> 8) & 0xff, ifDisable, status, hardware,
	    qupVersion, (ifDisable & 1) ? 1u : 0u);
	IOLog("MARBLE TOUCH PROBE: read-only snapshot complete; no GPIO, power, or SPI operation\n");
	return true;
}

static bool
takeSnapshot(void)
{
	IOMemoryDescriptor *gccDescriptor = NULL;
	IOMemoryMap *gccMap = mapReadOnly(kGccPhysical, kGccLength, &gccDescriptor);
	if (gccMap == NULL || gccMap->getVirtualAddress() == 0) {
		IOLog("MARBLE TOUCH PROBE: GCC read-only map failed; no registers read\n");
		if (gccMap != NULL) gccMap->release();
		if (gccDescriptor != NULL) gccDescriptor->release();
		return false;
	}
	const volatile uint32_t *gcc = (const volatile uint32_t *)gccMap->getVirtualAddress();

	/* WAIPIO/Cape GCC S4 source: CMD_RCGR 0x274e4, CFG is CMD+4. */
	const uint32_t sourceCfg = readReg(gcc, 0x274e8);
	const uint32_t sourceSel = (sourceCfg >> 8) & 0x7;
	const uint32_t sourceBranch = readReg(gcc, 0x274dc);
	const uint32_t masterAhb = readReg(gcc, 0x27004);
	const uint32_t slaveAhb = readReg(gcc, 0x27008);
	const uint32_t vote = readReg(gcc, 0x62008);
	const bool sourceSelValid = sourceSel == 0 || sourceSel == 1 || sourceSel == 6;
	const bool clocksReady = sourceSelValid &&
	    !(sourceBranch & kClockOff) && !(masterAhb & kClockOff) &&
	    !(slaveAhb & kClockOff) &&
	    (vote & (kSourceClockOn | kMasterAhbOn | kSlaveAhbOn)) ==
	    (kSourceClockOn | kMasterAhbOn | kSlaveAhbOn);

	IOLog("MARBLE TOUCH PROBE: gcc cfg=0x%08x src=%u s4=0x%08x m-ahb=0x%08x s-ahb=0x%08x vote=0x%08x ready=%u\n",
	    sourceCfg, sourceSel, sourceBranch, masterAhb, slaveAhb, vote,
	    clocksReady ? 1u : 0u);
	if (!clocksReady) {
		IOLog("MARBLE TOUCH PROBE: clocks not confirmed; SE and wrapper reads skipped\n");
		gccMap->release();
		gccDescriptor->release();
		return false;
	}
	gccMap->release();
	gccDescriptor->release();

	return takeSeSnapshot();
}

struct ClockProbeContext {
	volatile uint32_t *gcc;
};

static uint32_t
clockProbeRead(void *context, uint32_t offset)
{
	ClockProbeContext *probe = (ClockProbeContext *)context;
	return probe->gcc[offset / sizeof(uint32_t)];
}

static void
clockProbeWrite(void *context, uint32_t offset, uint32_t value)
{
	ClockProbeContext *probe = (ClockProbeContext *)context;
	probe->gcc[offset / sizeof(uint32_t)] = value;
	OSSynchronizeIO();
}

static void
clockProbeDelay(void *, unsigned usec)
{
	IODelay(usec);
}

static int
clockProbeReadSeInfo(void *)
{
	return takeSeSnapshot() ? 0 : -1;
}

static void
takeClockSnapshot(void)
{
	if (!OSCompareAndSwap(0, 1, &gMarbleTouchClockProbeState)) {
		IOLog("MARBLE TOUCH CLOCK: one-shot already active or consumed; skipped\n");
		return;
	}
	IOMemoryDescriptor *gccDescriptor = IOMemoryDescriptor::withPhysicalAddress(
	    kGccPhysical, kGccLength, kIODirectionOutIn);
	IOMemoryMap *gccMap = gccDescriptor != NULL ?
	    gccDescriptor->map(kIOMapInhibitCache) : NULL;
	if (gccMap == NULL || gccMap->getVirtualAddress() == 0) {
		IOLog("MARBLE TOUCH CLOCK: GCC read/write map failed; no clock writes\n");
		if (gccMap != NULL) gccMap->release();
		if (gccDescriptor != NULL) gccDescriptor->release();
		OSCompareAndSwap(1, 2, &gMarbleTouchClockProbeState);
		return;
	}
	ClockProbeContext context = {
	    (volatile uint32_t *)gccMap->getVirtualAddress() };
	marble_touch_probe_io io = {
	    &context, clockProbeRead, clockProbeWrite, clockProbeDelay,
	    clockProbeReadSeInfo };
	marble_touch_probe_report report;
	memset(&report, 0, sizeof(report));
	const int result = marble_spi_clock_probe(&io, &report);
	IOLog("MARBLE TOUCH CLOCK: result=%d cfg=0x%08x vote=0x%08x ahb=(0x%08x,0x%08x)\n",
	    result, report.source_cfg, report.vote_before, report.m_ahb_status,
	    report.s_ahb_status);
	IOLog("MARBLE TOUCH CLOCK: s4 before=0x%08x enabled=0x%08x restored=0x%08x polls=%u\n",
	    report.s4_status_before, report.s4_status_after,
	    report.s4_status_restored, report.poll_count);
	IOLog("MARBLE TOUCH CLOCK: owned=%u called=%u callback=%d restored=%u vote_after=0x%08x\n",
	    report.acquired_vote ? 1u : 0u, report.read_callback_called ? 1u : 0u,
	    report.read_callback_result, report.restored ? 1u : 0u,
	    report.vote_after_restore);
	gccMap->release();
	gccDescriptor->release();
	OSCompareAndSwap(1, 2, &gMarbleTouchClockProbeState);
}
} // namespace

bool
MarbleTouchProbe::start(IOService *provider)
{
	if (!IOService::start(provider)) {
		return false;
	}
	int enabled = 0;
	if (!PE_parse_boot_argn("marbletouchprobe", &enabled, sizeof(enabled))) {
		IOLog("MARBLE TOUCH PROBE: off (requires marbletouchprobe=1)\n");
		registerService();
		return true;
	}
	if (enabled == 1) {
		IOLog("MARBLE TOUCH PROBE: enabled; read-only GCC/GENI snapshot only\n");
		takeSnapshot();
	} else if (enabled == 2) {
		IOLog("MARBLE TOUCH CLOCK: mode2 temporary S4 vote; read-only SE info\n");
		takeClockSnapshot();
	} else if (enabled == 3) {
		IOLog("MARBLE TOUCH PREREQ: mode3 read-only SMMU/GPI/TLMM state; no DMA or writes\n");
		(void)marble_touch_prereq_snapshot();
	} else {
		IOLog("MARBLE TOUCH PROBE: off (requires marbletouchprobe=1, 2 or 3)\n");
	}
	registerService();
	return true;
}

#endif /* ARM64_BOARD_CONFIG_MARBLE */
