/* SPDX-License-Identifier: BSD-2-Clause-Patent */
#include "marble_smmu_stream.h"

#include <assert.h>
#include <stdio.h>

#define LEGACY_VALID (1u << 31)
#define EXIDVALID (1u << 10)

static uint32_t
smr_word(uint16_t id, uint16_t mask, int valid, marble_smmu_format format)
{
	uint32_t word = (uint32_t)id | ((uint32_t)mask << 16);
	if (format == MARBLE_SMMU_FORMAT_LEGACY && valid) {
		word |= LEGACY_VALID;
	}
	return word;
}

static uint32_t
s2cr_word(uint32_t type, uint8_t cb, int exidvalid)
{
	return (type << 16) | (uint32_t)cb | (exidvalid ? EXIDVALID : 0u);
}

static int
decode(uint32_t *smr, uint32_t *s2cr, size_t count, uint32_t sid,
	marble_smmu_format format, int verified, marble_smmu_stream_result *out)
{
	return marble_smmu_decode_stream(smr, s2cr, count, sid, format, verified, out);
}

static void
test_exact_and_masked_translation(void)
{
	uint32_t smr[2] = {0, smr_word(0x05a0, 0x000f, 1, MARBLE_SMMU_FORMAT_EXIDS)};
	uint32_t s2cr[2] = {0, s2cr_word(0, 7, 1)};
	marble_smmu_stream_result out;
	assert(decode(smr, s2cr, 2, 0x05a3, MARBLE_SMMU_FORMAT_EXIDS, 1, &out) == 0);
	assert(out.route == MARBLE_SMMU_ROUTE_TRANSLATE);
	assert(out.match_count == 1 && out.matched_index == 1 && out.context_bank == 7);
	assert(out.matched_smr == smr[1] && out.matched_s2cr == s2cr[1]);

	smr[1] = smr_word(0x5b6, 0, 1, MARBLE_SMMU_FORMAT_LEGACY);
	s2cr[1] = s2cr_word(0, 12, 0);
	assert(decode(smr, s2cr, 2, 0x5b6, MARBLE_SMMU_FORMAT_LEGACY, 1, &out) == 0);
	assert(out.route == MARBLE_SMMU_ROUTE_TRANSLATE && out.context_bank == 12);
}

static void
test_ambiguous_overlap_is_not_selected(void)
{
	uint32_t smr[2] = {
		smr_word(0x5a0, 0x000f, 1, MARBLE_SMMU_FORMAT_EXIDS),
		smr_word(0x5a3, 0x0000, 1, MARBLE_SMMU_FORMAT_EXIDS)
	};
	uint32_t s2cr[2] = {s2cr_word(0, 3, 1), s2cr_word(1, 4, 1)};
	marble_smmu_stream_result out;
	assert(decode(smr, s2cr, 2, 0x5a3, MARBLE_SMMU_FORMAT_EXIDS, 1, &out) == 0);
	assert(out.route == MARBLE_SMMU_ROUTE_AMBIGUOUS && out.match_count == 2);
	assert(out.context_bank == 0xffu);
}

static void
test_no_match_and_invalid_entry(void)
{
	uint32_t smr[1] = {smr_word(0x5a3, 0, 0, MARBLE_SMMU_FORMAT_LEGACY)};
	uint32_t s2cr[1] = {s2cr_word(0, 2, 1)};
	marble_smmu_stream_result out;
	assert(decode(smr, s2cr, 1, 0x5a3, MARBLE_SMMU_FORMAT_LEGACY, 1, &out) == 0);
	assert(out.route == MARBLE_SMMU_ROUTE_NONE && out.match_count == 0);

	smr[0] = smr_word(0x5a3, 0, 1, MARBLE_SMMU_FORMAT_LEGACY);
	s2cr[0] = s2cr_word(3, 2, 0);
	assert(decode(smr, s2cr, 1, 0x5a3, MARBLE_SMMU_FORMAT_LEGACY, 1, &out) == 0);
	assert(out.route == MARBLE_SMMU_ROUTE_INVALID_TYPE && out.context_bank == 2);
}

static void
test_fault_bypass_translate_routes(void)
{
	uint32_t smr[1] = {smr_word(0x5b6, 0, 1, MARBLE_SMMU_FORMAT_LEGACY)};
	uint32_t s2cr[1] = {s2cr_word(2, 0xff, 0)};
	marble_smmu_stream_result out;
	assert(decode(smr, s2cr, 1, 0x5b6, MARBLE_SMMU_FORMAT_LEGACY, 1, &out) == 0);
	assert(out.route == MARBLE_SMMU_ROUTE_FAULT && out.context_bank == 0xffu);
	s2cr[0] = s2cr_word(1, 0xff, 0);
	assert(decode(smr, s2cr, 1, 0x5b6, MARBLE_SMMU_FORMAT_LEGACY, 1, &out) == 0);
	assert(out.route == MARBLE_SMMU_ROUTE_BYPASS);
	s2cr[0] = s2cr_word(0, 9, 0);
	assert(decode(smr, s2cr, 1, 0x5b6, MARBLE_SMMU_FORMAT_LEGACY, 1, &out) == 0);
	assert(out.route == MARBLE_SMMU_ROUTE_TRANSLATE && out.context_bank == 9);
}

static void
test_format_and_input_rejections(void)
{
	uint32_t smr[1] = {0}, s2cr[1] = {0};
	marble_smmu_stream_result out;
	assert(decode(smr, s2cr, 1, 1, MARBLE_SMMU_FORMAT_LEGACY, 0, &out) ==
	    MARBLE_SMMU_DECODE_UNVERIFIED_FORMAT);
	assert(decode(smr, s2cr, 1, 1, MARBLE_SMMU_FORMAT_UNSPECIFIED, 1, &out) ==
	    MARBLE_SMMU_DECODE_BAD_ARGUMENT);
	assert(decode(smr, s2cr, 1, 1, (marble_smmu_format)99, 1, &out) ==
	    MARBLE_SMMU_DECODE_UNSUPPORTED_FORMAT);
	assert(decode(smr, s2cr, MARBLE_SMMU_MAX_SMES + 1u, 1,
	    MARBLE_SMMU_FORMAT_LEGACY, 1, &out) == MARBLE_SMMU_DECODE_COUNT_OVERFLOW);
	assert(decode(smr, s2cr, 1, 0x10000, MARBLE_SMMU_FORMAT_LEGACY, 1, &out) ==
	    MARBLE_SMMU_DECODE_BAD_SID);
	assert(decode(NULL, NULL, 1, 1, MARBLE_SMMU_FORMAT_LEGACY, 1, &out) ==
	    MARBLE_SMMU_DECODE_BAD_ARGUMENT);
	assert(decode(smr, s2cr, 1, 1, MARBLE_SMMU_FORMAT_LEGACY, 1, NULL) ==
	    MARBLE_SMMU_DECODE_BAD_ARGUMENT);
}

int
main(void)
{
	test_exact_and_masked_translation();
	test_ambiguous_overlap_is_not_selected();
	test_no_match_and_invalid_entry();
	test_fault_bypass_translate_routes();
	test_format_and_input_rejections();
	puts("Marble SMMU stream snapshot fixtures: PASS");
	return 0;
}
