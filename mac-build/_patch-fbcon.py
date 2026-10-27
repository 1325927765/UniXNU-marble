#!/usr/bin/env python3
"""Use DarwinBoot's GOP framebuffer when the ADT has no marble-fbcon node."""
from pathlib import Path
import sys

path = Path.home() / "unixnu-marble8796-build/xnu/pexpert/arm/pe_serial.c"
text = path.read_text()
old_probe = """static void
fbcon_probe(void)
{
	DTEntry entry;
	uint64_t const *reg;
	uint32_t const *val;
	unsigned int size;

	if (SecureDTFindEntry("name", "marble-fbcon", &entry) != kSuccess ||
	    SecureDTGetProperty(entry, "reg", (void const **)&reg, &size) != kSuccess || size < 16) {
		return;
	}
	if (SecureDTGetProperty(entry, "width", (void const **)&val, &size) == kSuccess) {
		fbcon_width = *val;
	}
	if (SecureDTGetProperty(entry, "height", (void const **)&val, &size) == kSuccess) {
		fbcon_height = *val;
	}
	if (SecureDTGetProperty(entry, "stride", (void const **)&val, &size) == kSuccess) {
		fbcon_stride = *val;
	}
	if (!fbcon_width || !fbcon_height || fbcon_stride < fbcon_width * 4) {
		return;
	}
	marble_early_mark(17, "fbcon config read; mapping");
	fbcon_base = (volatile uint32_t *)ml_io_map_wcomb(reg[0], reg[1]);
	marble_early_mark(18, "fbcon mapping returned");
	if (fbcon_base != NULL) {
		register_serial_functions(&marble_fbcon_serial_functions);
	}
}
"""
new_probe = """static int
fbcon_map_and_register(uint64_t phys, uint64_t map_size)
{
	uint64_t need;

	if (!fbcon_width || !fbcon_height || fbcon_stride < fbcon_width * 4) {
		return 0;
	}
	if (fbcon_stride > 0xffffffffu / fbcon_height) {
		return 0;
	}
	need = (uint64_t)fbcon_stride * fbcon_height;
	if (phys == 0 || map_size < need) {
		return 0;
	}
	marble_early_mark(17, "fbcon config read; mapping");
	fbcon_base = (volatile uint32_t *)ml_io_map_wcomb(phys, map_size);
	marble_early_mark(18, "fbcon mapping returned");
	if (fbcon_base == NULL) {
		return 0;
	}
	register_serial_functions(&marble_fbcon_serial_functions);
	return 1;
}

static void
fbcon_from_boot_video(void)
{
	/* Phone ADT has no marble-fbcon node. DarwinBoot copied the GOP
	 * framebuffer into boot_args, and PE_init_platform saved it here.
	 */
	if (PE_state.video.v_baseAddr == 0 || PE_state.video.v_depth < 32) {
		return;
	}
	if (PE_state.video.v_width > 0xffffffffu || PE_state.video.v_height > 0xffffffffu ||
	    PE_state.video.v_rowBytes > 0xffffffffu) {
		return;
	}
	fbcon_width = (uint32_t)PE_state.video.v_width;
	fbcon_height = (uint32_t)PE_state.video.v_height;
	fbcon_stride = (uint32_t)PE_state.video.v_rowBytes;
	(void)fbcon_map_and_register(PE_state.video.v_baseAddr, (uint64_t)fbcon_stride * fbcon_height);
}

static void
fbcon_probe(void)
{
	DTEntry entry;
	uint64_t const *reg;
	uint32_t const *val;
	unsigned int size;

	if (SecureDTFindEntry("name", "marble-fbcon", &entry) != kSuccess ||
	    SecureDTGetProperty(entry, "reg", (void const **)&reg, &size) != kSuccess || size < 16) {
		fbcon_from_boot_video();
		return;
	}
	if (SecureDTGetProperty(entry, "width", (void const **)&val, &size) == kSuccess) {
		fbcon_width = *val;
	}
	if (SecureDTGetProperty(entry, "height", (void const **)&val, &size) == kSuccess) {
		fbcon_height = *val;
	}
	if (SecureDTGetProperty(entry, "stride", (void const **)&val, &size) == kSuccess) {
		fbcon_stride = *val;
	}
	(void)fbcon_map_and_register(reg[0], reg[1]);
}
"""
old_gate = """	soc_base = pe_arm_get_soc_base_phys();

	if (soc_base == 0) {
		return 0;
	}

	PE_parse_boot_argn("disable-uart-irq", &disable_uart_irq, sizeof(disable_uart_irq));

	fbcon_probe();
"""
new_gate = """	soc_base = pe_arm_get_soc_base_phys();
	fbcon_probe();
	if (soc_base == 0) {
		if (gPESF == NULL) {
			return 0;
		}
		fns = gPESF;
		while (fns != NULL) {
			serial_do_transmit = 1;
			fns->init();
			fns = fns->next;
		}
		uart_initted = true;
		uart_sends_force_poll("MARBLE FBCON GOP\\n");
		return 1;
	}

	PE_parse_boot_argn("disable-uart-irq", &disable_uart_irq, sizeof(disable_uart_irq));
"""
old_done = """	/* Complete. */
	uart_initted = true;
	return 1;
}
"""
new_done = """	/* Complete. */
	uart_initted = true;
	uart_sends_force_poll("MARBLE FBCON GOP\\n");
	return 1;
}
"""
if old_probe not in text:
    sys.exit("fbcon_probe block not found")
if old_gate not in text:
    sys.exit("serial_init gate not found")
if old_done not in text:
    sys.exit("serial_init completion not found")
if text.count(old_done) != 1:
    sys.exit("serial_init completion is not unique")
text = text.replace(old_probe, new_probe, 1).replace(old_gate, new_gate, 1).replace(old_done, new_done, 1)
if "MARBLE FBCON GOP" not in text or "fbcon_from_boot_video" not in text:
    sys.exit("patch did not land")
path.write_text(text)
print("patched", path)
