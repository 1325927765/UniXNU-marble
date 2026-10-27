/* SPDX-License-Identifier: BSD-2-Clause-Patent */
#include "MarbleTouchProbeClock.h"

static int
ahb_ready(uint32_t status)
{
	return !(status & MARBLE_TOUCH_CLK_OFF) ||
	    (status & MARBLE_TOUCH_HWCG_ENABLE);
}

static int
s4_clock_on(uint32_t status)
{
	return !(status & MARBLE_TOUCH_CLK_OFF) ||
	    (status & MARBLE_TOUCH_NOC_STATUS_MASK) == MARBLE_TOUCH_NOC_STATUS_ON;
}

static int
read_se_snapshot(const marble_touch_probe_io *io, marble_touch_probe_report *report)
{
	report->read_callback_called = 1;
	report->read_callback_result = io->read_se_info(io->context);
	return report->read_callback_result == 0;
}

static int
restore_vote(const marble_touch_probe_io *io, marble_touch_probe_report *report)
{
	uint32_t current = io->read32(io->context, MARBLE_TOUCH_GCC_VOTE);
	io->write32(io->context, MARBLE_TOUCH_GCC_VOTE,
	    current & ~MARBLE_TOUCH_S4_VOTE);
	io->delay_us(io->context, 10u);
	report->vote_after_restore = io->read32(io->context, MARBLE_TOUCH_GCC_VOTE);
	report->s4_status_restored = io->read32(io->context, MARBLE_TOUCH_GCC_S4_CBCR);
	report->restored = !(report->vote_after_restore & MARBLE_TOUCH_S4_VOTE);
	return report->restored;
}

int
marble_spi_clock_probe(const marble_touch_probe_io *io,
	marble_touch_probe_report *report)
{
	uint32_t vote;
	int read_ok;

	if (io == 0 || report == 0 || io->read32 == 0 || io->write32 == 0 ||
	    io->delay_us == 0 || io->read_se_info == 0) {
		return MARBLE_TOUCH_PROBE_BAD_ARGUMENT;
	}
	/* Caller zeroes report. Require all existing SE and wrapper votes; never set bits 8/9. */
	report->source_cfg = io->read32(io->context, MARBLE_TOUCH_GCC_RCG_CFG);
	if (report->source_cfg != MARBLE_TOUCH_EXPECTED_CFG) {
		return MARBLE_TOUCH_PROBE_WRONG_SOURCE;
	}

	report->vote_before = io->read32(io->context, MARBLE_TOUCH_GCC_VOTE);
	report->m_ahb_status = io->read32(io->context, MARBLE_TOUCH_GCC_M_AHB_CBCR);
	report->s_ahb_status = io->read32(io->context, MARBLE_TOUCH_GCC_S_AHB_CBCR);
	if ((report->vote_before & (MARBLE_TOUCH_M_AHB_VOTE | MARBLE_TOUCH_S_AHB_VOTE |
	    MARBLE_TOUCH_CORE_VOTE | MARBLE_TOUCH_CORE2X_VOTE)) !=
	    (MARBLE_TOUCH_M_AHB_VOTE | MARBLE_TOUCH_S_AHB_VOTE |
	    MARBLE_TOUCH_CORE_VOTE | MARBLE_TOUCH_CORE2X_VOTE) ||
	    !ahb_ready(report->m_ahb_status) || !ahb_ready(report->s_ahb_status)) {
		return MARBLE_TOUCH_PROBE_AHB_NOT_READY;
	}

	report->had_vote = (report->vote_before & MARBLE_TOUCH_S4_VOTE) != 0;
	report->s4_status_before = io->read32(io->context, MARBLE_TOUCH_GCC_S4_CBCR);
	if (report->had_vote) {
		if (!s4_clock_on(report->s4_status_before)) {
			return MARBLE_TOUCH_PROBE_S4_NOT_READY;
		}
		read_ok = read_se_snapshot(io, report);
		return read_ok ? MARBLE_TOUCH_PROBE_OK : MARBLE_TOUCH_PROBE_READ_FAILED;
	}
	/* An unexpectedly running unvoted engine is not ours to take over. */
	if (s4_clock_on(report->s4_status_before)) {
		return MARBLE_TOUCH_PROBE_S4_NOT_READY;
	}

	/* Recheck immediately before claiming the vote; never clear an existing vote. */
	vote = io->read32(io->context, MARBLE_TOUCH_GCC_VOTE);
	if (vote & MARBLE_TOUCH_S4_VOTE) {
		report->had_vote = 1;
		report->s4_status_before = io->read32(io->context, MARBLE_TOUCH_GCC_S4_CBCR);
		if (!s4_clock_on(report->s4_status_before)) {
			return MARBLE_TOUCH_PROBE_S4_NOT_READY;
		}
		read_ok = read_se_snapshot(io, report);
		return read_ok ? MARBLE_TOUCH_PROBE_OK : MARBLE_TOUCH_PROBE_READ_FAILED;
	}
	report->s4_status_before = io->read32(io->context, MARBLE_TOUCH_GCC_S4_CBCR);
	if (s4_clock_on(report->s4_status_before)) {
		return MARBLE_TOUCH_PROBE_S4_NOT_READY;
	}

	io->write32(io->context, MARBLE_TOUCH_GCC_VOTE, vote | MARBLE_TOUCH_S4_VOTE);
	report->acquired_vote = 1;
	report->vote_after_enable = io->read32(io->context, MARBLE_TOUCH_GCC_VOTE);
	if (!(report->vote_after_enable & MARBLE_TOUCH_S4_VOTE)) {
		if (!restore_vote(io, report)) {
			return MARBLE_TOUCH_PROBE_RESTORE_FAILED;
		}
		return MARBLE_TOUCH_PROBE_S4_TIMEOUT;
	}
	for (report->poll_count = 0; report->poll_count < MARBLE_TOUCH_S4_POLL_LIMIT_US;
	     report->poll_count++) {
		report->s4_status_after = io->read32(io->context, MARBLE_TOUCH_GCC_S4_CBCR);
		if (s4_clock_on(report->s4_status_after)) {
			break;
		}
		io->delay_us(io->context, 1u);
	}
	read_ok = report->poll_count < MARBLE_TOUCH_S4_POLL_LIMIT_US;
	if (read_ok) {
		read_ok = read_se_snapshot(io, report);
	}
	if (!restore_vote(io, report)) {
		return MARBLE_TOUCH_PROBE_RESTORE_FAILED;
	}
	if (!read_ok) {
		return report->read_callback_result != 0 ?
		    MARBLE_TOUCH_PROBE_READ_FAILED : MARBLE_TOUCH_PROBE_S4_TIMEOUT;
	}
	return MARBLE_TOUCH_PROBE_OK;
}
