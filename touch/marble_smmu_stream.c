/* SPDX-License-Identifier: BSD-2-Clause-Patent */
#include "marble_smmu_stream.h"

#define SMMU_SMR_VALID_LEGACY  (1u << 31)
#define SMMU_SMR_MASK_SHIFT    16u
#define SMMU_SMR_MASK_LEGACY  0x7fffu /* bit 15 is VALID, so legacy mask is 30:16 */
#define SMMU_SMR_MASK_EXIDS   0xffffu /* EXIDS validity moves to S2CR */
#define SMMU_SMR_ID_MASK      0xffffu

#define SMMU_S2CR_TYPE_SHIFT   16u
#define SMMU_S2CR_TYPE_MASK    0x3u
#define SMMU_S2CR_CB_MASK      0xffu
#define SMMU_S2CR_EXIDVALID    (1u << 10)

static int
smr_matches(uint32_t smr, uint32_t s2cr, uint32_t sid,
	marble_smmu_format format)
{
	uint32_t id = smr & SMMU_SMR_ID_MASK;
	uint32_t mask = (smr >> SMMU_SMR_MASK_SHIFT) &
	    (format == MARBLE_SMMU_FORMAT_EXIDS ? SMMU_SMR_MASK_EXIDS :
	    SMMU_SMR_MASK_LEGACY);
	int valid = format == MARBLE_SMMU_FORMAT_EXIDS ?
	    ((s2cr & SMMU_S2CR_EXIDVALID) != 0) :
	    ((smr & SMMU_SMR_VALID_LEGACY) != 0);

	if (!valid) {
		return 0;
	}

	/* SMR mask bits are don't-care SID bits. */
	return (((sid ^ id) & ~mask) & SMMU_SMR_ID_MASK) == 0;
}

int
marble_smmu_decode_stream(const uint32_t *smr_words,
	const uint32_t *s2cr_words, size_t entry_count, uint32_t requested_sid,
	marble_smmu_format format, int format_verified,
	marble_smmu_stream_result *result)
{
	size_t i;
	uint32_t type;

	if (result == NULL) {
		return MARBLE_SMMU_DECODE_BAD_ARGUMENT;
	}
	result->route = MARBLE_SMMU_ROUTE_NONE;
	result->requested_sid = requested_sid;
	result->match_count = 0;
	result->matched_index = 0xffffffffu;
	result->matched_smr = 0;
	result->matched_s2cr = 0;
	result->context_bank = 0xffu;

	if ((entry_count != 0 && (smr_words == NULL || s2cr_words == NULL)) ||
	    format == MARBLE_SMMU_FORMAT_UNSPECIFIED) {
		return MARBLE_SMMU_DECODE_BAD_ARGUMENT;
	}
	if (!format_verified) {
		return MARBLE_SMMU_DECODE_UNVERIFIED_FORMAT;
	}
	if (format != MARBLE_SMMU_FORMAT_LEGACY &&
	    format != MARBLE_SMMU_FORMAT_EXIDS) {
		return MARBLE_SMMU_DECODE_UNSUPPORTED_FORMAT;
	}
	if (entry_count > MARBLE_SMMU_MAX_SMES) {
		return MARBLE_SMMU_DECODE_COUNT_OVERFLOW;
	}
	if (requested_sid > MARBLE_SMMU_SID_MASK) {
		return MARBLE_SMMU_DECODE_BAD_SID;
	}

	for (i = 0; i < entry_count; i++) {
		if (smr_matches(smr_words[i], s2cr_words[i], requested_sid, format)) {
			result->match_count++;
			if (result->match_count == 1) {
				result->matched_index = (uint32_t)i;
				result->matched_smr = smr_words[i];
				result->matched_s2cr = s2cr_words[i];
			}
		}
	}

	if (result->match_count == 0) {
		return MARBLE_SMMU_DECODE_OK;
	}
	if (result->match_count > 1) {
		result->route = MARBLE_SMMU_ROUTE_AMBIGUOUS;
		return MARBLE_SMMU_DECODE_OK;
	}

	type = (result->matched_s2cr >> SMMU_S2CR_TYPE_SHIFT) &
	    SMMU_S2CR_TYPE_MASK;
	result->context_bank = (uint8_t)(result->matched_s2cr & SMMU_S2CR_CB_MASK);
	switch (type) {
	case 0:
		result->route = MARBLE_SMMU_ROUTE_TRANSLATE;
		break;
	case 1:
		result->route = MARBLE_SMMU_ROUTE_BYPASS;
		break;
	case 2:
		result->route = MARBLE_SMMU_ROUTE_FAULT;
		break;
	default:
		result->route = MARBLE_SMMU_ROUTE_INVALID_TYPE;
		break;
	}
	return MARBLE_SMMU_DECODE_OK;
}
