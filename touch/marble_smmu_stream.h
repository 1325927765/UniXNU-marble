/* SPDX-License-Identifier: BSD-2-Clause-Patent */
#ifndef MARBLE_SMMU_STREAM_H
#define MARBLE_SMMU_STREAM_H

#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define MARBLE_SMMU_MAX_SMES 128u
#define MARBLE_SMMU_SID_MASK 0xffffu

typedef enum marble_smmu_format {
	MARBLE_SMMU_FORMAT_UNSPECIFIED = 0,
	MARBLE_SMMU_FORMAT_LEGACY = 1,
	MARBLE_SMMU_FORMAT_EXIDS = 2
} marble_smmu_format;

typedef enum marble_smmu_route {
	MARBLE_SMMU_ROUTE_NONE = 0,
	MARBLE_SMMU_ROUTE_TRANSLATE = 1,
	MARBLE_SMMU_ROUTE_BYPASS = 2,
	MARBLE_SMMU_ROUTE_FAULT = 3,
	MARBLE_SMMU_ROUTE_AMBIGUOUS = 4,
	MARBLE_SMMU_ROUTE_INVALID_TYPE = 5
} marble_smmu_route;

typedef enum marble_smmu_decode_error {
	MARBLE_SMMU_DECODE_OK = 0,
	MARBLE_SMMU_DECODE_BAD_ARGUMENT = -1,
	MARBLE_SMMU_DECODE_UNVERIFIED_FORMAT = -2,
	MARBLE_SMMU_DECODE_UNSUPPORTED_FORMAT = -3,
	MARBLE_SMMU_DECODE_COUNT_OVERFLOW = -4,
	MARBLE_SMMU_DECODE_BAD_SID = -5
} marble_smmu_decode_error;

typedef struct marble_smmu_stream_result {
	marble_smmu_route route;
	uint32_t requested_sid;
	uint32_t match_count;
	uint32_t matched_index;
	uint32_t matched_smr;
	uint32_t matched_s2cr;
	uint8_t context_bank;
} marble_smmu_stream_result;

/*
 * Decode a caller-supplied, already-read SMMUv2 SMR/S2CR snapshot.
 * format must explicitly match an IDR0-derived feature check by the caller.
 * No MMIO, probing, matching-group mutation, or IOMMU programming occurs here.
 */
int marble_smmu_decode_stream(const uint32_t *smr_words,
	const uint32_t *s2cr_words, size_t entry_count, uint32_t requested_sid,
	marble_smmu_format format, int format_verified,
	marble_smmu_stream_result *result);

#ifdef __cplusplus
}
#endif

#endif
