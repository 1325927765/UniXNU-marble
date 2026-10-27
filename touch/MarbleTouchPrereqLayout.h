/* SPDX-License-Identifier: BSD-2-Clause-Patent */
#ifndef MARBLE_TOUCH_PREREQ_LAYOUT_H
#define MARBLE_TOUCH_PREREQ_LAYOUT_H

#include <stdint.h>

#define MARBLE_TOUCH_PREREQ_DTS_SMR_LIMIT 120u
#define MARBLE_TOUCH_PREREQ_MAX_SMR_LIMIT 128u
#define MARBLE_TOUCH_PREREQ_TLMM_BASE 0x0f000000u
#define MARBLE_TOUCH_PREREQ_TLMM_REG_BASE 0x00100000u
#define MARBLE_TOUCH_PREREQ_TLMM_REG_SIZE 0x1000u
#define MARBLE_TOUCH_PREREQ_TLMM_MAP_SIZE 0x00116000u
#define MARBLE_TOUCH_PREREQ_GPI_BASE 0x00900000u
#define MARBLE_TOUCH_PREREQ_GPI_MAP_SIZE 0x00060000u
#define MARBLE_TOUCH_PREREQ_GPI_TX0_CONTEXT 0x00010000u
#define MARBLE_TOUCH_PREREQ_GPI_RX1_CONTEXT 0x00010080u
#define MARBLE_TOUCH_PREREQ_GPI_EVENT_CONTEXT 0x00011000u
#define MARBLE_TOUCH_PREREQ_GPI_TYPE_IRQ_STATUS 0x00013080u
#define MARBLE_TOUCH_PREREQ_GPI_CH_IRQ_STATUS 0x00013090u
#define MARBLE_TOUCH_PREREQ_GPI_EV_IRQ_STATUS 0x00013094u
#define MARBLE_TOUCH_PREREQ_GPI_GLOBAL_IRQ_STATUS 0x00013100u
#define MARBLE_TOUCH_PREREQ_GPI_GENERAL_IRQ_STATUS 0x00013118u

static inline uint32_t
marble_touch_prereq_smr_count(uint32_t hardware_count)
{
	uint32_t count = hardware_count;
	if (count > MARBLE_TOUCH_PREREQ_DTS_SMR_LIMIT)
		count = MARBLE_TOUCH_PREREQ_DTS_SMR_LIMIT;
	if (count > MARBLE_TOUCH_PREREQ_MAX_SMR_LIMIT)
		count = MARBLE_TOUCH_PREREQ_MAX_SMR_LIMIT;
	return count;
}

static inline uint32_t
marble_touch_prereq_tlmm_cfg_offset(uint32_t pin)
{
	return MARBLE_TOUCH_PREREQ_TLMM_REG_BASE +
	    MARBLE_TOUCH_PREREQ_TLMM_REG_SIZE * pin;
}

static inline int
marble_touch_prereq_tlmm_pin_fits(uint32_t pin)
{
	uint32_t cfg = marble_touch_prereq_tlmm_cfg_offset(pin);
	return pin >= 16u && pin <= 21u && cfg + 4u + sizeof(uint32_t) <=
	    MARBLE_TOUCH_PREREQ_TLMM_MAP_SIZE;
}

static inline int
marble_touch_prereq_gpi_word_fits(uint32_t offset)
{
	return (offset & 3u) == 0 && offset <=
	    MARBLE_TOUCH_PREREQ_GPI_MAP_SIZE - sizeof(uint32_t);
}

static inline int
marble_touch_prereq_gpi_context_valid(uint32_t config, uint32_t length,
	uint32_t base_low, uint32_t base_high)
{
	return config != 0xffffffffu && length != 0xffffffffu &&
	    base_low != 0xffffffffu && base_high != 0xffffffffu;
}

static inline int
marble_touch_prereq_sid_fits(uint32_t sid, int exids, uint32_t sid_bits)
{
	uint32_t width;
	if (sid > 0xffffu)
		return 0;
	if (exids) {
		width = 1u << 16;
	} else {
		if (sid_bits > 15u)
			return 0;
		width = 1u << sid_bits;
	}
	return sid < width;
}

#endif
