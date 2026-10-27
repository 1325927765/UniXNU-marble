# Marble Goodix SPI board evidence (read-only)

This note resolves board resource references for a future bounded diagnostic. It is source evidence only: no MMIO, SPI command, GPIO, power, or device action was performed.

## Provenance and SoC applicability

- Board snapshot: `research/hardware-live-20261023-connected/marble-live.dts` (saved live Marble/F5 DTS). Root model says SM7475 at line 4. The GCC node at lines 788–800 is `compatible = "qcom,cape-gcc"`, base `0x100000`, provider phandle `0x24`; the active device node is `spi@990000`, lines 12628–12646, with child `m16t-touch@0`, lines 12648–12672.
- Applicable local kernel source: `research/touch-marble-official`, MiCode Xiaomi `marble-s-oss`, HEAD `48952ed36228217531482b39d5bef13e7fd808ec`. This repository is sparsely checked out: the files under `drivers/clk/qcom` are absent from the working directory, but the Git blobs are available and were read directly with `git -C research/touch-marble-official show HEAD:drivers/clk/qcom/gcc-waipio.c` and `...:include/dt-bindings/clock/qcom,gcc-waipio.h`. Its `gcc-waipio.c` match table accepts both `qcom,waipio-gcc` and `qcom,cape-gcc`, and has a `gcc_cape_fixup`; therefore the Cape-compatible binding is directly covered by the Marble branch. This is not an SM8550 inference. The controller IDs below are taken from this Marble branch's Waipio/Cape binding and driver, not an unrelated SM8550 GCC source.
- Goodix compiled-module evidence: `research/hardware-goodix-recovery-20261025/elf-audit.md`, auditing recovered `.ko` SHA-256 `096437302c7b81fe06a4ec1dfc793777d88a75cc5b06e3c3db8393a7f77aa372`. ELF audit explicitly identifies Berlin_D version record address `0x10014`, length 28 bytes, checksum validator U8_LE. It confirms framing is 8 bytes (`F1 + BE32 address + 3 FF`) before the 28-byte payload. Total SPI transfer length is therefore 36 bytes; the previous 16-byte proposal was incorrect and is superseded.

## Controller clocks

The `spi@990000` node declares, in order, `clock-names = "se-clk", "m-ahb", "s-ahb"` and `clocks = <0x24 0x5e 0x24 0x86 0x24 0x87>` (DTS lines 12628–12646). The provider is GCC phandle `0x24` (lines 788–800). In the Marble branch's `include/dt-bindings/clock/qcom,gcc-waipio.h`:

- `0x5e` / decimal 94 = `GCC_QUPV3_WRAP0_S4_CLK` (not S5).
- `0x86` / decimal 134 = `GCC_QUPV3_WRAP_0_M_AHB_CLK`.
- `0x87` / decimal 135 = `GCC_QUPV3_WRAP_0_S_AHB_CLK`.

This matches the controller's physical address `0x990000`, the fourth SE in wrapper 0 (`spi@980000` through `spi@990000`; live DTS aliases label the latter `qupv3_se4_spi` at lines 33754–33760). In `drivers/clk/qcom/gcc-waipio.c`, `gcc_qupv3_wrap0_s4_clk_src` uses command register `0x274e4`, and its branch uses halt register `0x274dc`, enable register `0x62008`, bit 14. Wrapper-0 master/slave AHB branches use halt/HWCG registers `0x27004`/`0x27008`, enable register `0x62008`, bits 6/7. These are reference driver definitions, not permission to access MMIO.

The S4 source uses the shared frequency table `ftbl_gcc_qupv3_wrap0_s0_clk_src` (`gcc-waipio.c:776–788`): 7.3728, 14.7456, 19.2, 29.4912, 32, 48, 64, 75, 80, 96, and 100 MHz. S4 selects the same table at lines 907–912. The DT and this source do not establish which rate is currently selected at runtime. Do not choose a rate or divider from the DTS alone. Before any diagnostic, the adapter must establish the configured source rate/index from the live controller state or explicitly configure it through a reviewed board clock path; the SPI cap of 15 MHz is only a maximum.

## Pins, GPIO, and power

- Controller bus pin states: DTS controller lines 12637–12639 references active `0x606` and sleep `0x608`. The pinctrl definitions at lines 5178–5190 show active `gpio16`, `gpio17`, `gpio18`, function `qup4`, drive 6 mA, bias disabled. Sleep state at lines 5193–5205 changes these pins to GPIO function, drive 6 mA, bias disabled.
- Chip-select pin states: controller's second active/sleep phandles `0x607`/`0x609` are the Goodix CS states; lines 5148–5175 map active GPIO19 to `qup4`, drive 16 mA, pull-up, and sleep GPIO19 to GPIO function, drive 16 mA, pull-up.
- Touch pinctrl: child lines 12655–12657 references active `0x60a`; suspend `0x60b` and `0x60c`. Definitions at lines 5133–5145 configure GPIO20/21, GPIO function, 8 mA, pull-up. Suspend definitions at lines 4343–4377 put GPIO20 and GPIO21 in GPIO mode, 2 mA, pull-down.
- Touch IRQ/reset are child lines 12653–12664: GPIO provider phandle `0x3c`, interrupt pin 21 with flags `0x2008`, falling-edge IRQ flag 2; reset GPIO20. GPIO controller definition lines 1349–1359 is Cape pinctrl base `0x0f000000`, size `0x01000000`, GPIO and interrupt controller. The exact interrupt translation/controller programming is not implemented in QcomGeniSpi.
- Supplies: touch child lines 12658–12661 attaches `iovdd-supply = <0x302>` and `avdd-supply = <0x309>`. Provider targets are `pm8350c_l2` at DTS lines 6019–6026: fixed min/max/init 1,800,000 µV; and `pm8350c_l9` at lines 6145–6152: fixed min/max/init 3,200,000 µV. These identify rails and nominal values only; they do not by themselves specify safe XNU sequencing/current/load timing. A no-toggle diagnostic must require the panel/touch rails already be on; otherwise stop.

## Smallest bounded read candidate and unknowns

After a board adapter can safely confirm the existing clock/pin/rail state, the lowest-scope controller probe remains one Goodix version-register read: address `0x10014`, Berlin_D 28-byte payload, 36 total SPI bytes at no more than 15 MHz. Use standard framing established by the recovered ELF; validate the 28-byte U8_LE checksum before reporting a version. No Goodix writes, reset toggles, firmware upload, or event/IRQ service are required for this read. The physical version value has not been captured.

Unknowns that block a concrete XNU transaction today: current source-clock rate and selected parent/divider; controller firmware/FIFO mode and whether PIO is usable; live enable state of clock branches and both rails; exact operation/compatibility of DTS interrupt flags in legacy XNU; and the regulator/pinctrl sequencing contracts. Existing shared QcomGeniSpi operations do not implement these board services. Do not guess any of them.

The local Stage 2 clock snapshot prototype only temporarily votes S4 bit 14 after exact source-CFG and pre-existing clock checks. It does not write the RCG, AHB votes, or GPIO/PMIC registers. It also requires pre-existing vote bits 8/9 (core/core2x) before its combined SE and wrapper read callback; it never enables or clears those bits. GCC's shared HLOS vote register is an RMW surface: the probe preserves unrelated bits by rereading on restore, but cannot distinguish another owner's concurrent claim on the same S4 bit. Any use therefore requires confirming the target XNU image has no other user of this S4 vote and that no concurrent owner can claim it. The one-shot guard only serializes this probe instance; it does not establish global clock ownership.

## Source anchors

- Saved live DTS: controller/touch `research/hardware-live-20261023-connected/marble-live.dts:12628-12672`, GCC provider `:788-800`, GPIO provider `:1349-1359`, pin configs `:4343-4377`, `:5133-5194`, rails `:6019-6026`, `:6145-6152`.
- Marble kernel source at HEAD `48952ed36228217531482b39d5bef13e7fd808ec`: `include/dt-bindings/clock/qcom,gcc-waipio.h:106,146-147` clock constants; `drivers/clk/qcom/gcc-waipio.c:776-788` rate table, `:907-912` S4 source, `:2734-2749` S4 branch, `:3110-3136` AHB branches, and `:3982-3987` Cape/waipio compatible table.
- Recovered module audit: `research/hardware-goodix-recovery-20261025/elf-audit.md`, Berlin_D version read subsection.
- Reusable shared SPI component: `research/reference-qcom-geni-spi` at `eac47baefe6a5d2368a70351e6ad1b6361bedbe2`; source callback/API contract in `GeniSpi.h:164-222`; FIFO-disabled/Pio-vs-DMA guard in `GeniSpi.c:74-80`.
