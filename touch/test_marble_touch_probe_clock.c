/* SPDX-License-Identifier: BSD-2-Clause-Patent */
#include "MarbleTouchProbeClock.h"

#include <assert.h>
#include <stdio.h>
#include <string.h>

typedef struct fake_mmio {
	uint32_t cfg;
	uint32_t vote;
	uint32_t m_ahb;
	uint32_t s_ahb;
	uint32_t s4;
	unsigned writes;
	unsigned delays;
	unsigned delayed_us;
	unsigned s4_reads_after_enable;
	unsigned s4_on_after_reads;
	unsigned callback_count;
	int callback_result;
	int mutate_other_vote_bit;
	int ignore_s4_set;
	int ignore_s4_clear;
	uint32_t written_values[4];
} fake_mmio;

static uint32_t
fake_read(void *context, uint32_t offset)
{
	fake_mmio *f = (fake_mmio *)context;
	switch (offset) {
	case MARBLE_TOUCH_GCC_RCG_CFG: return f->cfg;
	case MARBLE_TOUCH_GCC_VOTE: return f->vote;
	case MARBLE_TOUCH_GCC_M_AHB_CBCR: return f->m_ahb;
	case MARBLE_TOUCH_GCC_S_AHB_CBCR: return f->s_ahb;
	case MARBLE_TOUCH_GCC_S4_CBCR:
		if (f->vote & MARBLE_TOUCH_S4_VOTE) {
			f->s4_reads_after_enable++;
			if (f->s4_on_after_reads != 0 &&
			    f->s4_reads_after_enable >= f->s4_on_after_reads) {
				return f->s4 & ~MARBLE_TOUCH_CLK_OFF;
			}
		}
		return f->s4;
	default:
		assert(!"Unexpected fake MMIO read offset");
		return 0;
	}
}

static void
fake_write(void *context, uint32_t offset, uint32_t value)
{
	fake_mmio *f = (fake_mmio *)context;
	assert(offset == MARBLE_TOUCH_GCC_VOTE);
	assert(f->writes < 4);
	f->written_values[f->writes++] = value;
	if ((f->ignore_s4_set && (value & MARBLE_TOUCH_S4_VOTE)) ||
	    (f->ignore_s4_clear && !(value & MARBLE_TOUCH_S4_VOTE))) return;
	f->vote = value;
}

static void
fake_delay(void *context, unsigned usec)
{
	fake_mmio *f = (fake_mmio *)context;
	f->delays++;
	f->delayed_us += usec;
}

static int
fake_read_se(void *context)
{
	fake_mmio *f = (fake_mmio *)context;
	f->callback_count++;
	if (f->mutate_other_vote_bit) {
		f->vote |= 1u << 20;
	}
	return f->callback_result;
}

static void
initialize(fake_mmio *f, marble_touch_probe_io *io)
{
	memset(f, 0, sizeof(*f));
	f->cfg = MARBLE_TOUCH_EXPECTED_CFG;
	f->vote = MARBLE_TOUCH_M_AHB_VOTE | MARBLE_TOUCH_S_AHB_VOTE |
	    (1u << 8) | (1u << 9);
	f->m_ahb = 0;
	f->s_ahb = MARBLE_TOUCH_CLK_OFF | MARBLE_TOUCH_HWCG_ENABLE;
	f->s4 = MARBLE_TOUCH_CLK_OFF;
	f->s4_on_after_reads = 2;
	io->context = f;
	io->read32 = fake_read;
	io->write32 = fake_write;
	io->delay_us = fake_delay;
	io->read_se_info = fake_read_se;
}

static int
run(marble_touch_probe_io *io, marble_touch_probe_report *r)
{
	memset(r, 0, sizeof(*r));
	return marble_spi_clock_probe(io, r);
}

static void
test_success_with_hwcg_and_other_vote_mutation(void)
{
	fake_mmio f;
	marble_touch_probe_io io;
	marble_touch_probe_report r;
	initialize(&f, &io);
	f.mutate_other_vote_bit = 1;
	uint32_t before = f.vote;
	assert(run(&io, &r) == MARBLE_TOUCH_PROBE_OK);
	assert(f.callback_count == 1 && f.writes == 2);
	assert(f.written_values[0] == (before | MARBLE_TOUCH_S4_VOTE));
	assert(f.written_values[1] == ((before | (1u << 20))));
	assert((f.vote & MARBLE_TOUCH_S4_VOTE) == 0);
	assert(f.vote & (1u << 20));
	assert((f.vote & (MARBLE_TOUCH_M_AHB_VOTE | MARBLE_TOUCH_S_AHB_VOTE)) ==
	    (MARBLE_TOUCH_M_AHB_VOTE | MARBLE_TOUCH_S_AHB_VOTE));
	assert(r.acquired_vote && r.restored && r.poll_count == 1);
	assert(r.read_callback_called && !(r.s4_status_after & MARBLE_TOUCH_CLK_OFF));
	assert(r.s4_status_restored & MARBLE_TOUCH_CLK_OFF);
	assert(f.delayed_us == 11);
}

static void
test_timeout_restores_vote(void)
{
	fake_mmio f;
	marble_touch_probe_io io;
	marble_touch_probe_report r;
	initialize(&f, &io);
	f.s4_on_after_reads = 0;
	uint32_t before = f.vote;
	assert(run(&io, &r) == MARBLE_TOUCH_PROBE_S4_TIMEOUT);
	assert(f.callback_count == 0 && f.writes == 2);
	assert(f.vote == before && r.restored && r.poll_count == 200);
	assert(f.delayed_us == 210);
}

static void
test_wrong_source_and_missing_ahb_are_noops(void)
{
	fake_mmio f;
	marble_touch_probe_io io;
	marble_touch_probe_report r;
	initialize(&f, &io);
	f.cfg ^= 1u;
	assert(run(&io, &r) == MARBLE_TOUCH_PROBE_WRONG_SOURCE);
	assert(f.writes == 0 && f.callback_count == 0);
	initialize(&f, &io);
	f.vote &= ~MARBLE_TOUCH_S_AHB_VOTE;
	assert(run(&io, &r) == MARBLE_TOUCH_PROBE_AHB_NOT_READY);
	assert(f.writes == 0 && f.callback_count == 0);
	initialize(&f, &io);
	f.vote &= ~MARBLE_TOUCH_CORE2X_VOTE;
	assert(run(&io, &r) == MARBLE_TOUCH_PROBE_AHB_NOT_READY);
	assert(f.writes == 0 && f.callback_count == 0);
	initialize(&f, &io);
	f.s_ahb = MARBLE_TOUCH_CLK_OFF;
	assert(run(&io, &r) == MARBLE_TOUCH_PROBE_AHB_NOT_READY);
	assert(f.writes == 0 && f.callback_count == 0);
}

static void
test_preexisting_s4_vote_is_never_cleared(void)
{
	fake_mmio f;
	marble_touch_probe_io io;
	marble_touch_probe_report r;
	initialize(&f, &io);
	f.vote |= MARBLE_TOUCH_S4_VOTE;
	f.s4 = 0;
	uint32_t before = f.vote;
	assert(run(&io, &r) == MARBLE_TOUCH_PROBE_OK);
	assert(f.callback_count == 1 && f.writes == 0);
	assert(f.vote == before && r.had_vote && !r.acquired_vote && !r.restored);
}

static void
test_unvoted_running_clock_is_not_claimed(void)
{
	fake_mmio f;
	marble_touch_probe_io io;
	marble_touch_probe_report r;
	initialize(&f, &io);
	f.s4 = 0;
	assert(run(&io, &r) == MARBLE_TOUCH_PROBE_S4_NOT_READY);
	assert(f.writes == 0 && f.callback_count == 0 && !r.acquired_vote);
}

static void
test_vote_write_readback_failures(void)
{
	fake_mmio f;
	marble_touch_probe_io io;
	marble_touch_probe_report r;
	initialize(&f, &io);
	f.ignore_s4_set = 1;
	assert(run(&io, &r) == MARBLE_TOUCH_PROBE_S4_TIMEOUT);
	assert(f.callback_count == 0 && f.writes == 2 && r.restored);
	initialize(&f, &io);
	f.ignore_s4_clear = 1;
	assert(run(&io, &r) == MARBLE_TOUCH_PROBE_RESTORE_FAILED);
	assert(f.callback_count == 1 && f.writes == 2 && !r.restored);
}

static void
test_callback_failure_still_restores_owned_vote(void)
{
	fake_mmio f;
	marble_touch_probe_io io;
	marble_touch_probe_report r;
	initialize(&f, &io);
	f.callback_result = -77;
	assert(run(&io, &r) == MARBLE_TOUCH_PROBE_READ_FAILED);
	assert(f.callback_count == 1 && f.writes == 2 && r.restored);
	assert(!(f.vote & MARBLE_TOUCH_S4_VOTE));
}

int
main(void)
{
	test_success_with_hwcg_and_other_vote_mutation();
	test_timeout_restores_vote();
	test_wrong_source_and_missing_ahb_are_noops();
	test_preexisting_s4_vote_is_never_cleared();
	test_unvoted_running_clock_is_not_claimed();
	test_vote_write_readback_failures();
	test_callback_failure_still_restores_owned_vote();
	puts("Marble stage2 clock probe host fixtures: PASS");
	return 0;
}
