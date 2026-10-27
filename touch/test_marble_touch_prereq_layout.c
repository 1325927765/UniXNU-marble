/* SPDX-License-Identifier: BSD-2-Clause-Patent */
#include "MarbleTouchPrereqLayout.h"

#include <assert.h>
#include <stdio.h>

int
main(void)
{
	assert(marble_touch_prereq_smr_count(0) == 0);
	assert(marble_touch_prereq_smr_count(1) == 1);
	assert(marble_touch_prereq_smr_count(120) == 120);
	assert(marble_touch_prereq_smr_count(121) == 120);
	assert(marble_touch_prereq_smr_count(255) == 120);
	for (uint32_t pin = 16; pin <= 21; pin++) {
		assert(marble_touch_prereq_tlmm_pin_fits(pin));
		assert(marble_touch_prereq_tlmm_cfg_offset(pin) ==
		    0x100000u + pin * 0x1000u);
	}
	assert(!marble_touch_prereq_tlmm_pin_fits(15));
	assert(!marble_touch_prereq_tlmm_pin_fits(22));
	assert(marble_touch_prereq_tlmm_cfg_offset(16) == 0x110000u);
	assert(marble_touch_prereq_tlmm_cfg_offset(21) == 0x115000u);
	assert(MARBLE_TOUCH_PREREQ_GPI_BASE == 0x900000u);
	assert(MARBLE_TOUCH_PREREQ_GPI_MAP_SIZE == 0x60000u);
	assert(MARBLE_TOUCH_PREREQ_GPI_TX0_CONTEXT == 0x10000u);
	assert(MARBLE_TOUCH_PREREQ_GPI_RX1_CONTEXT == 0x10080u);
	assert(MARBLE_TOUCH_PREREQ_GPI_EVENT_CONTEXT == 0x11000u);
	assert(MARBLE_TOUCH_PREREQ_GPI_TYPE_IRQ_STATUS == 0x13080u);
	assert(MARBLE_TOUCH_PREREQ_GPI_CH_IRQ_STATUS == 0x13090u);
	assert(MARBLE_TOUCH_PREREQ_GPI_EV_IRQ_STATUS == 0x13094u);
	assert(MARBLE_TOUCH_PREREQ_GPI_GLOBAL_IRQ_STATUS == 0x13100u);
	assert(MARBLE_TOUCH_PREREQ_GPI_GENERAL_IRQ_STATUS == 0x13118u);
	assert(marble_touch_prereq_gpi_word_fits(0x13118u));
	assert(!marble_touch_prereq_gpi_word_fits(0x60000u));
	assert(!marble_touch_prereq_gpi_word_fits(0x13119u));
	assert(marble_touch_prereq_gpi_context_valid(0, 0, 0, 0));
	assert(!marble_touch_prereq_gpi_context_valid(0xffffffffu, 0, 0, 0));
	assert(!marble_touch_prereq_gpi_context_valid(0, 0xffffffffu, 0, 0));
	assert(!marble_touch_prereq_gpi_context_valid(0, 0, 0xffffffffu, 0));
	assert(!marble_touch_prereq_gpi_context_valid(0, 0, 0, 0xffffffffu));
	assert(marble_touch_prereq_sid_fits(0x05a3u, 1, 0u));
	assert(marble_touch_prereq_sid_fits(0x05b6u, 1, 0u));
	assert(marble_touch_prereq_sid_fits(0xffffu, 1, 0u));
	assert(!marble_touch_prereq_sid_fits(0x10000u, 1, 15u));
	assert(marble_touch_prereq_sid_fits(0x05a3u, 0, 12u));
	assert(marble_touch_prereq_sid_fits(0x05b6u, 0, 11u));
	assert(!marble_touch_prereq_sid_fits(0x05b6u, 0, 10u));
	assert(!marble_touch_prereq_sid_fits(0xffffu, 0, 16u));
	puts("Marble prerequisite layout fixtures: PASS");
	return 0;
}
