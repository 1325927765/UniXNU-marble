/* SPDX-License-Identifier: BSD-2-Clause-Patent */
#ifndef MARBLE_TOUCH_PROBE_CLOCK_H
#define MARBLE_TOUCH_PROBE_CLOCK_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define MARBLE_TOUCH_GCC_RCG_CFG       0x274e8u
#define MARBLE_TOUCH_GCC_S4_CBCR       0x274dcu
#define MARBLE_TOUCH_GCC_M_AHB_CBCR    0x27004u
#define MARBLE_TOUCH_GCC_S_AHB_CBCR    0x27008u
#define MARBLE_TOUCH_GCC_VOTE          0x62008u

#define MARBLE_TOUCH_EXPECTED_CFG      0x00100000u
#define MARBLE_TOUCH_S4_VOTE           (1u << 14)
#define MARBLE_TOUCH_M_AHB_VOTE        (1u << 6)
#define MARBLE_TOUCH_S_AHB_VOTE        (1u << 7)
#define MARBLE_TOUCH_CORE_VOTE         (1u << 8)
#define MARBLE_TOUCH_CORE2X_VOTE       (1u << 9)
#define MARBLE_TOUCH_CLK_OFF           (1u << 31)
#define MARBLE_TOUCH_HWCG_ENABLE       (1u << 1)
#define MARBLE_TOUCH_NOC_STATUS_MASK   (7u << 28)
#define MARBLE_TOUCH_NOC_STATUS_ON     (2u << 28)
#define MARBLE_TOUCH_S4_POLL_LIMIT_US  200u

typedef struct marble_touch_probe_io {
	void *context;
	uint32_t (*read32)(void *context, uint32_t offset);
	void (*write32)(void *context, uint32_t offset, uint32_t value);
	void (*delay_us)(void *context, unsigned delay);
	int (*read_se_info)(void *context);
} marble_touch_probe_io;

typedef struct marble_touch_probe_report {
	uint32_t source_cfg;
	uint32_t vote_before;
	uint32_t m_ahb_status;
	uint32_t s_ahb_status;
	uint32_t s4_status_before;
	uint32_t vote_after_enable;
	uint32_t s4_status_after;
	uint32_t s4_status_restored;
	uint32_t vote_after_restore;
	unsigned poll_count;
	int had_vote;
	int acquired_vote;
	int read_callback_result;
	int read_callback_called;
	int restored;
} marble_touch_probe_report;

enum marble_touch_probe_result {
	MARBLE_TOUCH_PROBE_OK = 0,
	MARBLE_TOUCH_PROBE_BAD_ARGUMENT = -1,
	MARBLE_TOUCH_PROBE_WRONG_SOURCE = -2,
	MARBLE_TOUCH_PROBE_AHB_NOT_READY = -3,
	MARBLE_TOUCH_PROBE_S4_NOT_READY = -4,
	MARBLE_TOUCH_PROBE_S4_TIMEOUT = -5,
	MARBLE_TOUCH_PROBE_READ_FAILED = -6,
	MARBLE_TOUCH_PROBE_RESTORE_FAILED = -7
};

/* Sets/restores only S4 vote bit 14; never changes the RCG or AHB votes. */
int marble_spi_clock_probe(const marble_touch_probe_io *io,
	marble_touch_probe_report *report);

#ifdef __cplusplus
}
#endif

#endif
