# Source-backed Marble hardware inventory

The DTS is a sanitized, deliberately incomplete observed-hardware subset. It is
not a dump, a complete SoC DTSI, an Apple identity tree or a verified boot tree.
No hardware serial, seed, MAC address or owner data is copied.

Source cross-check: Xiaomi marble-s-oss commit
48952ed36228217531482b39d5bef13e7fd808ec and the maintainer's qualified F5 tree.
The public touch notes identify exact controller/clock/pinctrl source files.

| Resource | Observed value / scope |
| --- | --- |
| Boot CPU | Affinity 0 only; SMP is not enabled by this port |
| PSCI | arm,psci-1.0; smc |
| GIC | Distributor 0x17100000/0x10000, redistributors 0x17180000/0x200000, stride 0x40000 |
| Virtual timer | 19200000 Hz; PPI 11, INTID 27 |
| UFS | Host 0x1d84000/0x3000, ICE 0x1d88000/0x8000, PHY 0x1d90000/0x9000; SPI 265 |
| SPI / Goodix | SE 0x990000/0x4000; SPI 605; child CS0, 15MHz maximum, GPIO20 reset/GPIO21 IRQ |
| GCC | cape-gcc at 0x100000/0x1f4200; SPI clock IDs 94/134/135 |
| TLMM | cape-pinctrl at 0x0f000000/0x01000000; Cape GPIO bank offset 0x100000 plus pin*0x1000 |
| GPI | 0x900000/0x60000; TX0/RX1, SEID4, protocol1, 64 TREs, static-channel argument2 |
| SMMU | apps block 0x15000000/0x100000, second region 0x151ce000/0x20; 120 SMR override |
| DMA roles | GPI ring SID0x5b6; QUP wrapper payload SID0x5a3. These are distinct contexts, not proof of valid mappings |
| Framebuffer | Obtained from firmware GOP at runtime; no fixed framebuffer address published |

The peripheral nodes remain disabled: their format 2 driver/clock/power/PHY and
OS ABI integration is not complete. The GPIO IRQ flags are preserved as the
observed value, without claiming a tested XNU interrupt implementation. The
GPIO20 reset flag/polarity and power sequencing still require review before
using this descriptive tree to drive hardware.

Memory and reservations are omitted rather than set to a guessed zero range or
a single device's RAM map. A future shared SM7475 DTSI and board runtime handoff
must describe real owned/reserved ranges for the tested SKU. The successful
legacy path used a firmware-allocated 512MiB window; a DRAM address envelope is
not installed memory capacity. The complete format 2 memory/ADT conversion
remains blocked and is recorded in porting.toml.

The source-only DTS compile is a syntax/binding-shape check, not proof of a
working kernel or safe DMA. No MMIO or phone access occurs during that check.
