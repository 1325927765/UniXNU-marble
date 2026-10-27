/*
 * Read-only Marble prerequisites snapshot. Source evidence and hardware
 * accessibility limits are documented in MARBLE-TOUCH-PREREQ-SNAPSHOT.md.
 */
#include <pexpert/arm64/board_config.h>

#if defined(ARM64_BOARD_CONFIG_MARBLE)
#include <IOKit/IOLib.h>
#include <IOKit/IOMemoryDescriptor.h>
#include <IOKit/IOMapTypes.h>
#include <libkern/OSAtomic.h>

#include "MarbleTouchPrereq.h"
#include "MarbleTouchPrereqLayout.h"
#include "marble_smmu_stream.h"

namespace {
static const uint64_t kAppsSmmuPhysical = 0x15000000ULL;
static const uint64_t kAppsSmmuMapLength = 0x1000ULL;
static const uint32_t kAppsSmmuId0 = 0x020u;
static const uint32_t kAppsSmmuId1 = 0x024u;
static const uint32_t kAppsSmmuId2 = 0x028u;
static const uint32_t kSmmuSmrBase = 0x800u;
static const uint32_t kSmmuS2crBase = 0xc00u;
static const uint32_t kSmmuDtsSmeLimit = MARBLE_TOUCH_PREREQ_DTS_SMR_LIMIT;
static const uint32_t kId0Sms = 1u << 27;
static const uint32_t kId0NumSidBits = 0x0fu << 9;
static const uint32_t kId0Exids = 1u << 8;
static const uint32_t kId0NumSmrg = 0xffu;
static const uint64_t kGccPhysical = 0x00100000ULL;
static const uint64_t kGccMapLength = 0x00063000ULL;
static const uint32_t kGccVoteOffset = 0x62008u;
static const uint32_t kRequiredExistingGccVotes = (1u << 6) | (1u << 7) |
	(1u << 8) | (1u << 9);
static volatile UInt32 gPrereqSnapshotState = 0; /* one-shot: unused/running/done */

static uint32_t
readReg(const volatile uint32_t *base, uint32_t offset)
{
	return base[offset / sizeof(uint32_t)];
}

static IOMemoryMap *
mapReadOnly(uint64_t physical, uint64_t length,
	IOMemoryDescriptor **descriptor)
{
	*descriptor = IOMemoryDescriptor::withPhysicalAddress(
	    physical, length, kIODirectionIn);
	if (*descriptor == NULL)
		return NULL;
	return (*descriptor)->map(kIOMapInhibitCache | kIOMapReadOnly);
}

static const char *
routeName(marble_smmu_route route)
{
	switch (route) {
	case MARBLE_SMMU_ROUTE_TRANSLATE: return "translate";
	case MARBLE_SMMU_ROUTE_BYPASS: return "bypass";
	case MARBLE_SMMU_ROUTE_FAULT: return "fault";
	case MARBLE_SMMU_ROUTE_AMBIGUOUS: return "ambiguous";
	case MARBLE_SMMU_ROUTE_INVALID_TYPE: return "invalid-type";
	default: return "none";
	}
}

static bool
captureSmmuSnapshot(void)
{
	IOMemoryDescriptor *descriptor = NULL;
	IOMemoryMap *map = mapReadOnly(kAppsSmmuPhysical,
	    kAppsSmmuMapLength, &descriptor);
	if (map == NULL || map->getVirtualAddress() == 0) {
		IOLog("MARBLE TOUCH PREREQ: apps SMMU read-only map failed\n");
		if (map != NULL) map->release();
		if (descriptor != NULL) descriptor->release();
		return false;
	}
	const volatile uint32_t *smmu =
	    (const volatile uint32_t *)map->getVirtualAddress();
	const uint32_t id0 = readReg(smmu, kAppsSmmuId0);
	const uint32_t id1 = readReg(smmu, kAppsSmmuId1);
	const uint32_t id2 = readReg(smmu, kAppsSmmuId2);
	IOLog("MARBLE TOUCH PREREQ: SMMU ID0=0x%08x ID1=0x%08x ID2=0x%08x\n",
	    id0, id1, id2);

	if (id0 == 0 || id0 == 0xffffffffu || id1 == 0 || id1 == 0xffffffffu ||
	    id2 == 0 || id2 == 0xffffffffu || !(id0 & kId0Sms)) {
		IOLog("MARBLE TOUCH PREREQ: SMMU ID registers unsupported/invalid; SME reads skipped\n");
		map->release();
		descriptor->release();
		return false;
	}

	const bool exids = (id0 & kId0Exids) != 0;
	const uint32_t hardwareCount = id0 & kId0NumSmrg;
	const uint32_t count = marble_touch_prereq_smr_count(hardwareCount);
	if (hardwareCount == 0 || count == 0) {
		IOLog("MARBLE TOUCH PREREQ: zero SMRG count; SME reads skipped\n");
		map->release();
		descriptor->release();
		return false;
	}
	const uint32_t sidBits = (id0 & kId0NumSidBits) >> 9;
	const uint32_t sidWidth = exids ? (1u << 16) : (1u << sidBits);
	if (!marble_touch_prereq_sid_fits(0x05a3u, exids, sidBits) ||
	    !marble_touch_prereq_sid_fits(0x05b6u, exids, sidBits)) {
		IOLog("MARBLE TOUCH PREREQ: ID0 SID width=%u cannot represent target IDs; SME reads skipped\n",
		    sidWidth);
		map->release();
		descriptor->release();
		return false;
	}
	IOLog("MARBLE TOUCH PREREQ: SMS=1 EXIDS=%u NUMSMRG=%u SME snapshot count=%u (DTS cap=%u)\n",
	    exids ? 1u : 0u, hardwareCount, count, kSmmuDtsSmeLimit);

	uint32_t smrWords[MARBLE_SMMU_MAX_SMES];
	uint32_t s2crWords[MARBLE_SMMU_MAX_SMES];
	for (uint32_t i = 0; i < count; i++) {
		smrWords[i] = readReg(smmu, kSmmuSmrBase + i * sizeof(uint32_t));
		s2crWords[i] = readReg(smmu, kSmmuS2crBase + i * sizeof(uint32_t));
	}
	map->release();
	descriptor->release();

	const marble_smmu_format format = exids ? MARBLE_SMMU_FORMAT_EXIDS :
	    MARBLE_SMMU_FORMAT_LEGACY;
	const uint32_t targetSids[2] = {0x05a3u, 0x05b6u};
	for (unsigned i = 0; i < 2; i++) {
		marble_smmu_stream_result result;
		const int decode = marble_smmu_decode_stream(smrWords, s2crWords,
		    count, targetSids[i], format, 1, &result);
		if (decode != MARBLE_SMMU_DECODE_OK) {
			IOLog("MARBLE TOUCH PREREQ: SID 0x%04x decode error=%d\n",
			    targetSids[i], decode);
			continue;
		}
		if (result.match_count != 0) {
			IOLog("MARBLE TOUCH PREREQ: SID 0x%04x route=%s matches=%u first=%u SMR=0x%08x S2CR=0x%08x CB=%u\n",
			    targetSids[i], routeName(result.route), result.match_count,
			    result.matched_index, result.matched_smr,
			    result.matched_s2cr, static_cast<unsigned>(result.context_bank));
		} else {
			IOLog("MARBLE TOUCH PREREQ: SID 0x%04x route=none matches=0\n",
			    targetSids[i]);
		}
	}
	IOLog("MARBLE TOUCH PREREQ: no context-bank config or translation-table reads performed\n");
	return true;
}

static bool
captureGpiSnapshot(void)
{
	/* Guard against touching the GPI block unless the observed SE/core votes remain present. */
	IOMemoryDescriptor *gccDescriptor = NULL;
	IOMemoryMap *gccMap = mapReadOnly(kGccPhysical, kGccMapLength,
	    &gccDescriptor);
	if (gccMap == NULL || gccMap->getVirtualAddress() == 0) {
		IOLog("MARBLE TOUCH PREREQ: GCC vote guard map failed; GPI reads skipped\n");
		if (gccMap != NULL) gccMap->release();
		if (gccDescriptor != NULL) gccDescriptor->release();
		return false;
	}
	const volatile uint32_t *gcc =
	    (const volatile uint32_t *)gccMap->getVirtualAddress();
	const uint32_t vote = readReg(gcc, kGccVoteOffset);
	gccMap->release();
	gccDescriptor->release();
	const bool votesPresent =
	    (vote & kRequiredExistingGccVotes) == kRequiredExistingGccVotes;
	IOLog("MARBLE TOUCH PREREQ: GCC existing vote guard=0x%08x required=0x%08x pass=%u (not proof of GPI supply)\n",
	    vote, kRequiredExistingGccVotes, votesPresent ? 1u : 0u);
	if (!votesPresent) {
		IOLog("MARBLE TOUCH PREREQ: GCC vote guard failed; GPI reads skipped\n");
		return false;
	}

	IOMemoryDescriptor *gpiDescriptor = NULL;
	IOMemoryMap *gpiMap = mapReadOnly(MARBLE_TOUCH_PREREQ_GPI_BASE,
	    MARBLE_TOUCH_PREREQ_GPI_MAP_SIZE, &gpiDescriptor);
	if (gpiMap == NULL || gpiMap->getVirtualAddress() == 0) {
		IOLog("MARBLE TOUCH PREREQ: GPI read-only map failed\n");
		if (gpiMap != NULL) gpiMap->release();
		if (gpiDescriptor != NULL) gpiDescriptor->release();
		return false;
	}
	const volatile uint32_t *gpi =
	    (const volatile uint32_t *)gpiMap->getVirtualAddress();
	const uint32_t contextOffsets[3] = {
		MARBLE_TOUCH_PREREQ_GPI_TX0_CONTEXT,
		MARBLE_TOUCH_PREREQ_GPI_RX1_CONTEXT,
		MARBLE_TOUCH_PREREQ_GPI_EVENT_CONTEXT
	};
	const char *const contextNames[3] = {"tx0", "rx1", "event0"};
	bool valid = true;
	for (unsigned i = 0; i < 3; i++) {
		const uint32_t offset = contextOffsets[i];
		if (!marble_touch_prereq_gpi_word_fits(offset + 0x0u) ||
		    !marble_touch_prereq_gpi_word_fits(offset + 0x4u) ||
		    !marble_touch_prereq_gpi_word_fits(offset + 0x8u) ||
		    !marble_touch_prereq_gpi_word_fits(offset + 0xcu)) {
			IOLog("MARBLE TOUCH PREREQ: GPI %s context outside map bounds\n",
			    contextNames[i]);
			valid = false;
			continue;
		}
		const uint32_t config = readReg(gpi, offset);
		const uint32_t length = readReg(gpi, offset + 0x4u);
		const uint32_t baseLow = readReg(gpi, offset + 0x8u);
		const uint32_t baseHigh = readReg(gpi, offset + 0xcu);
		const uint32_t state = (config >> 20) & 0xfu;
		const uint32_t ee = (config >> 4) & 0xfu;
		IOLog("MARBLE TOUCH PREREQ: GPI %s cfg=0x%08x state=%u ee=%u len=0x%08x ring_base=0x%08x%08x\n",
		    contextNames[i], config, state, ee, length, baseHigh, baseLow);
		if (!marble_touch_prereq_gpi_context_valid(config, length,
		    baseLow, baseHigh))
			valid = false;
	}

	const uint32_t statusOffsets[5] = {
		MARBLE_TOUCH_PREREQ_GPI_TYPE_IRQ_STATUS,
		MARBLE_TOUCH_PREREQ_GPI_CH_IRQ_STATUS,
		MARBLE_TOUCH_PREREQ_GPI_EV_IRQ_STATUS,
		MARBLE_TOUCH_PREREQ_GPI_GLOBAL_IRQ_STATUS,
		MARBLE_TOUCH_PREREQ_GPI_GENERAL_IRQ_STATUS
	};
	uint32_t status[5];
	for (unsigned i = 0; i < 5; i++) {
		if (!marble_touch_prereq_gpi_word_fits(statusOffsets[i])) {
			IOLog("MARBLE TOUCH PREREQ: GPI status offset outside map bounds\n");
			valid = false;
			status[i] = 0xffffffffu;
			continue;
		}
		status[i] = readReg(gpi, statusOffsets[i]);
		if (status[i] == 0xffffffffu)
			valid = false;
	}
	IOLog("MARBLE TOUCH PREREQ: GPI status type=0x%08x ch_irq=0x%08x ev_irq=0x%08x global=0x%08x gpii=0x%08x (read-only; clear regs untouched)\n",
	    status[0], status[1], status[2], status[3], status[4]);
	gpiMap->release();
	gpiDescriptor->release();
	if (!valid)
		IOLog("MARBLE TOUCH PREREQ: GPI snapshot contained all-ones/invalid values\n");
	return valid;
}

static bool
captureTlmmSnapshot(void)
{
	IOMemoryDescriptor *descriptor = NULL;
	IOMemoryMap *map = mapReadOnly(MARBLE_TOUCH_PREREQ_TLMM_BASE,
	    MARBLE_TOUCH_PREREQ_TLMM_MAP_SIZE, &descriptor);
	if (map == NULL || map->getVirtualAddress() == 0) {
		IOLog("MARBLE TOUCH PREREQ: Cape TLMM read-only map failed\n");
		if (map != NULL) map->release();
		if (descriptor != NULL) descriptor->release();
		return false;
	}
	const volatile uint32_t *tlmm =
	    (const volatile uint32_t *)map->getVirtualAddress();
	bool valid = true;
	for (uint32_t pin = 16; pin <= 21; pin++) {
		if (!marble_touch_prereq_tlmm_pin_fits(pin)) {
			IOLog("MARBLE TOUCH PREREQ: TLMM pin %u out of snapshot bounds\n", pin);
			map->release();
			descriptor->release();
			return false;
		}
		const uint32_t cfgOffset = marble_touch_prereq_tlmm_cfg_offset(pin);
		const uint32_t cfg = readReg(tlmm, cfgOffset);
		const uint32_t io = readReg(tlmm, cfgOffset + 4u);
		if (cfg == 0xffffffffu || io == 0xffffffffu)
			valid = false;
		const uint32_t mux = (cfg >> 2) & 0xfu; /* Cape PINGROUP mux_bit=2 */
		IOLog("MARBLE TOUCH PREREQ: TLMM gpio%u cfg=0x%08x mux=%u io=0x%08x\n",
		    pin, cfg, mux, io);
	}
	map->release();
	descriptor->release();
	return valid;
}
} // namespace

extern "C" int
marble_touch_prereq_snapshot(void)
{
	if (!OSCompareAndSwap(0, 1, &gPrereqSnapshotState)) {
		IOLog("MARBLE TOUCH PREREQ: one-shot snapshot already active/consumed\n");
		return -1;
	}
	int errors = 0;
	if (!captureSmmuSnapshot()) errors |= 1;
	if (!captureGpiSnapshot()) errors |= 4;
	if (!captureTlmmSnapshot()) errors |= 2;
	IOLog("MARBLE TOUCH PREREQ: complete error_mask=%d; read-only prerequisite snapshot only\n",
	    errors);
	OSCompareAndSwap(1, 2, &gPrereqSnapshotState);
	return errors;
}

#endif /* ARM64_BOARD_CONFIG_MARBLE */
