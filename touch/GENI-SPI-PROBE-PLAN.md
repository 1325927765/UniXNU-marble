# Marble Goodix initial transport diagnostic

Local engineering plan, 2026-10-25. No live SPI result or ready-to-boot touch
driver is claimed. Keep this unfinished work out of the public community repo.

## Verified clock and controller readout

Video `20261025_214554.mp4` confirms the mode-2 temporary S4 vote test:
result 0; S4 status changed `0x80004220 -> 0x00004220 -> 0x80004220`;
owned/called/restored were all 1, callback returned 0, and the vote word
returned to `0x400283c0`. This verifies the clock/readout/restore operation,
not a Goodix transaction. Dense tail frames show the Hello lettering animation
and swipe prompt on a clean background.

The SE reports firmware `0x00000102`, SPI protocol 1, IF_DISABLE `0x1`, status
0, HW_PARAM0 `0x20102864`, QUP version `0x300b0000`. FIFO is disabled. The
matching Marble Linux SPI driver selects **GPI/GSI DMA**, not SE DMA, for this
state. Do not enable `allow_fifo_disabled` or assume the shared core's SE-DMA
implementation is an alternative. See [MARBLE-GPI-DMA-PATH.md](MARBLE-GPI-DMA-PATH.md).

## Current diagnostic implementation

`MarbleTouchProbe.cpp` is a separate first-stage snapshot service, enabled
only by `marbletouchprobe=1`. It uses read-only mappings, logs GCC branch,
source selection and vote registers, and skips GENI/wrapper info reads unless
the known clock branches and votes are enabled. It does not initialize the
controller or issue a Goodix read. No TLMM or regulator access is present.
The GCC source-selection whitelist `{0,1,6}` was checked against
`gcc_parent_map_0` in the pinned Marble source: TCXO, GPLL0 main and GPLL0 even.
It is a selection check, not a frequency measurement.

`install_marble_touch_probe.py` defaults to dry-run, inserts the complete
IOResources personality before the existing panic-platform dictionary,
preserves file modes, and rolls back modified files after write failures.
Its structural/write-failure fixture passes. The shared `QcomGeniSpi` source
also passes its supplied host register-model test (PIO and SE DMA); that is
not a hardware result or proof of legacy-XNU integration.

## Recovery observations collected on 2026-10-25

The serial-selected collector confirmed Marble Recovery, `spi0.0` at
`/soc/spi@990000/m16t-touch@0`, compatible `goodix,9916r-spi`, driver `gtx8_spi`.
The parent controller's runtime status was `suspended`; the child's status
was `unsupported` (not a failure of the controller).

Debugfs was initially unmounted. The parent operator mounted only debugfs
read-only, collected bounded summaries, and unmounted it after each capture;
no block filesystem, GPIO, regulator or SPI register was changed. The idle
summary reports S4 clock source/branch rate 100,000,000 Hz with enable/prepare
counts zero. That is a configured/cached clock rate, not a live SPI bit rate.
Bus GPIO16..19 were in GPIO mode while suspended. The regulator summary
reports pm8350c_l2 enabled at 1800 mV and pm8350c_l9 enabled at 3224 mV; the
latter is the reported regulator value, not the DTS nominal 3200 mV. These
Recovery observations do not establish what UEFI leaves enabled for XNU.

The valid bounded capture is private
`research/hardware-goodix-recovery-20261025/spi-state-debugfs-pinconf-v2.json`.
The earlier `...-pinconf.json` capture contains a GPIO-filter regex error and
must not be used as evidence of absent pin configuration. The corrected
filter was run against the real device. Pinconf records themselves contained
no extra configuration text beyond the GPIO labels.

## Reviewed inputs

- Saved live DTS: `research/hardware-live-20261023-connected/marble-live.dts`.
  Controller at line 12628, Goodix child at line 12648.
- Shared core: `UniXNU/QcomGeniSpi` commit
  `eac47baefe6a5d2368a70351e6ad1b6361bedbe2`, BSD-2-Clause-Patent.
  It is a candidate implementation; the inspected catalog declares the newer
  iPadOS ABI, not a verified legacy-XNU8796/F5 integration.
- Matched Recovery module: see the private host ELF audit and `README.md`.
  The selected BERLIN_D branch uses an eight-byte read prefix and a 28-byte
  version record at `0x10014`. It does not use the shorter version length
  suggested by an earlier generic protocol note.

## Board resources established from the saved DTS

| Resource | Value | Meaning / limit |
| --- | --- | --- |
| Serial engine | `spi@990000`, window `0x4000` | Requires an XNU MMIO mapping and running clocks |
| Controller interrupt | `<0 0x25d 4>` | Raw DT interrupt tuple, not an XNU interrupt index |
| Clock references | `<0x24 0x5e>`, `<0x24 0x86>`, `<0x24 0x87>` | Named se-clk, m-ahb, s-ahb; not rates or register offsets |
| Active bus pins | GPIO16/17/18 plus CS GPIO19, function qup4 | Phandles `0x606` and `0x607`; pinmux encoding still needs platform support |
| Touch reset / interrupt | GPIO20 / GPIO21 | GPIO controller `0x3c`; lifecycle and IRQ integration absent |
| Child chip select / speed cap | CS0 / 15 MHz | A cap, not evidence of the current source clock |
| Power references | iovdd `0x302`, avdd `0x309` | Resolve regulator targets and lifecycle before operating rails |
| TX/RX DMA | Referenced through provider `0xc7` | GPI DMA tuples are not directly usable by the shared SE-DMA implementation |

## Staged verification

1. Bind board MMIO/delay callbacks and establish clock, pin and power state
   from platform source and bounded observations. Do not assume that Android
   recovery state survives a reboot into UEFI/XNU.
2. Read shared-core controller information only when clock access is known to
   be valid. Reject an unexpected protocol or unsupported FIFO state. Do not
   override the FIFO-disabled guard to force progress.
3. Review controller setup writes separately from the read-only Goodix
   command. Polling avoids an initial interrupt-handler dependency, but still
   needs correct pinmux, power, source clock and transfer completion limits.
   If PIO is unavailable, DMA additionally requires verified addresses,
   mappings and cache callbacks; do not reuse the DT GPI tuples as SE DMA.
4. Issue one version read: eight framing bytes plus 28 response bytes,
   **36 bytes total (288 SPI clock cycles)**. Header:
   `F1 00 01 00 14 FF FF FF`. Validate the response checksum and structure,
   record failure or raw result, then stop. No register scan, Goodix register
   writes, rail/reset transitions or firmware upload belongs in this probe.
5. Only after transport/version and IC-info parsing are validated, obtain the
   dynamic report address and connect reports to the decoder and existing
   `marble_hid_touch()` path. Test contact release as well as movement, and
   validate coordinate mapping before enabling gestures.

`goodix9916r_spi_read.{c,h}` supplies bounded framing through a caller-provided
callback. Its fake-callback tests do not establish controller compatibility or
live SPI access. The XNU board adapter is still missing; this plan is not an
executable test package.
