# POCO F5 Goodix 9916R touch bring-up notes

## Latest physical-device observation

Video `20261025_214554.mp4` subsequently verified temporary S4 clock activation,
SPI-controller information reads and restoration of the original vote. The
controller reports FIFO disabled, so the next missing component is the GPI/GSI
DMA path, including its two DMA/IOMMU mapping roles; the shared SPI core's
SE-DMA implementation is not a validated fallback. Recovery collection also
confirmed the live GPI TX/RX channel bindings. See
[MARBLE-GPI-DMA-PATH.md](MARBLE-GPI-DMA-PATH.md). No Goodix register transaction
or iOS physical touch input has yet been demonstrated.

On 2026-10-25 the user reported that the latest temporary boot reached the
iPhone Hello interface, with a clean background and no scrolling console text
or flicker. Physical touchscreen input still did not respond. This confirms
the visible quiet-console result by user observation, not by a new captured
video. Setup bypass has not been demonstrated; the device is still at Hello.
The image did not include a completed physical touch backend.

## Shared SPI implementation found during format-2 migration

The current official UniXNU catalog at revision
`16e592abee8a550dec8154ed1f38b5ebc4f16213` lists
[`QcomGeniSpi`](https://github.com/UniXNU/QcomGeniSpi), pinned there to
`eac47baefe6a5d2368a70351e6ad1b6361bedbe2`. It provides reusable GENI SPI
controller operations and requires board MMIO/DMA callbacks, clocks and pins.
The catalog declares only the iPadOS 17 ABI and no verified devices. This is a
candidate core for a Marble adapter; it is not a working Goodix/F5 driver and
has not been integrated into the current XNU 8796 kernel. The earlier absence
of a SPI driver referred to the existing local legacy kernel checkout.

## Evidence and source provenance

The saved live F5 device tree is `research/hardware-live-20261023-connected/marble-live.dts`, node `m16t-touch@0` under the Qualcomm SPI controller, with `compatible = "goodix,9916r-spi"`. Its properties specify SPI max 15 MHz, IRQ GPIO 21, reset GPIO 20, panel 1080x2400, and firmware/config names `goodix_firmware_TM.bin` and `goodix_cfg_group_TM.bin`.

The official Xiaomi source repository is [MiCode/Xiaomi_Kernel_OpenSource](https://github.com/MiCode/Xiaomi_Kernel_OpenSource). The exact `goodix,9916r-spi` compatible is present in the `ruby-s-oss` branch source `drivers/input/touchscreen/goodix_9916r/goodix_brl_spi.c` (branch commit `914ba8403bb3a957ed37b99dcecdbafce9d16121`). Its Goodix header states GPL version 2; retain its copyright/license headers if porting any code. That branch is for another Xiaomi product, so its protocol code is a reference, not yet proof of compatibility with this board's firmware/config. Its core selects `goodix,firmware-namea/b` and `goodix,config-namea/b` based on board GPIOs; the saved F5 node instead exposes singular `goodix,firmware-name` and `goodix,config-name`. Resolve that ABI difference before treating the driver as drop-in.

The official `marble-s-oss` branch at `48952ed36228217531482b39d5bef13e7fd808ec` contains `drivers/input/touchscreen/goodix_9916`, but its SPI driver matches `xiaomi,l12-spi`; it does **not** match the F5's `goodix,9916r-spi` string. This is why the exact ruby source is the closer published protocol reference even though marble's own branch has a similarly named driver.

Additional public source confirmation: Pzqqt's [Melt Kernel notes](https://pzqqt.github.io/2025/02/04/Melt-Kernel-%E6%9B%B4%E6%96%B0%E6%97%A5%E8%AE%B0.html) call out `goodix,9916r-spi` and point to MiCode's `ruby-s-oss` driver. The Xiaomi repo branch/device mapping is listed in the official [MiCode source README](https://github.com/MiCode/Xiaomi_Kernel_OpenSource/blob/README/README.md).

### Published SPI protocol notes (reference only)

From the pinned ruby branch's `goodix_brl_spi.c` and `goodix_brl_hw.c`:

- Register addresses are 32-bit big-endian in the SPI command header. Read opcode is `0xF1`, write opcode `0xF0`. The normal/BRL read helper sends four `0xFF` dummy bytes after the address; a second helper uses a one-byte-shorter prefix. The controller type selects which path applies, so a hand-built probe must not guess a framing variant.
- The BRL mode switch writes then reads register `0xC900` with value `0x01`; reset/clock setup also writes registers such as `0xD808`, `0xD807`, and `0xD806`. These are initialization writes, not safe diagnostic reads.
- The published `brl_read_version` reads a 16-byte firmware-version structure at `0x1000C` for its BRL-A type or `0x10014` otherwise, retries three times, and rejects it unless its trailing two bytes match the sum of preceding bytes modulo 65536 (little-endian checksum). Those addresses are source-defined per IC type, not a confirmed Marble-safe ID probe.
- The event-data base is not a fixed literal in the event handler: it comes from the IC-info block (`touch_data_addr`) after reading and checksumming IC metadata at `0x10068` (BRL-A) or `0x10070` (other type). The handler reads an 8-byte head plus two points and trailing checksum from that dynamic address, then reads remaining point records for more than two contacts. An XNU port must resolve/validate the IC type and metadata before reading events; never assume an address from this note is the live report address.
- The only justified transport cap from the saved F5 DTS is 15 MHz (`0xe4e1c0`). The Ruby code's source/header is GPL-2. Keep it as protocol evidence; do not copy it into the APSL XNU tree without a deliberate license-compatible implementation decision.

No SPI transaction is issued by the preparation tools below.

## Recovery evidence from 2026-10-25

The read-only collector was run against ADB serial `<redacted-device-serial>`; the recovery properties identify `marble`. It found the active `goodix_core` module and the actual Goodix sysfs binding `spi0.0` (`spi:9916r-spi`) -> `gtx8_spi`; the input device is `/dev/input/event7`, `goodix_ts`. The module is ELF64/AArch64, `v1.2.2`, `vermagic=5.10.160-gki-g953173920402 ... aarch64`, `license=GPL v2`, SHA256 `096437302c7b81fe06a4ec1dfc793777d88a75cc5b06e3c3db8393a7f77aa372`. This identity matches the public Ruby source version, but is not a byte-for-byte build comparison.

An additional host-only ELF audit is saved at `research/hardware-goodix-recovery-20261025/elf-audit.md`. The recovered `.ko` is not stripped and exposes `goodix_get_ic_type`, `goodix_spi_probe`, `goodix_spi_read_bra`, `goodix_spi_read`, `brl_read_version`, `brl_get_ic_info`, and `brl_event_handler`. Comparing their AArch64 disassembly with the pinned Ruby source establishes that the F5 compatible `goodix,9916r-spi` selects enum 6 (`IC_TYPE_BERLIN_D`), the regular 8-byte read prefix (`F1 + BE32 address + FF FF FF`), firmware-version record address `0x10014`, and IC-info address `0x10070`. The actual version-record bytes and raw SPI reports were not collected; this identifies the module's code branch and is not a hardware probe result.

The collector pulled the requested firmware and config files. Both firmware variants are 223744 bytes and share SHA256 `97786dd7f3014a0da2c822a3d875466bd793210398d67be3bb24fa0c72db964a`. The configs are both 1429 bytes but differ: default SHA256 `580371a8454eec5425106b9b7a9edb73b7b9ef95eba4173fe748b3195791f9d2`; `_Second` SHA256 `9755d23ca873edba91fc2ffe457fd7b09622faaf3643151b36ca299ff6a101e0`. The module embeds references to `_Second.bin`; preserve both config variants until the panel/GPIO selection path is confirmed.

`research/hardware-goodix-recovery-20261025/event7-15s.txt` is a read-only, 15-second `getevent` capture. The detailed summary is in `event7-15s-summary.json`. `/dev/input/event7` advertises X 0..10800, Y 0..24000, slots 0..9, and direct input. The capture contains active X/Y movement and BTN_TOUCH transitions; observed X 1212..9906 and Y 1016..4377. This proves the Android/recovery event path works. These events are already-decoded Linux input reports; they do not show raw controller packets and must not be treated as evidence that an XNU SPI probe works.

The public Goodix input code sets ABS ranges from IC-reported `screen_max_x/y`, not only DT panel dimensions. When those exceed panel max, it preserves the higher-resolution coordinates; otherwise it scales by the panel/screen ratio. The live 10800x24000 ranges vs DTS 1080x2400 panel maxima are consistent with a 10x firmware coordinate grid. The captured finger paths did not touch the physical edges, so they cannot calibrate origin or edge transform.

The current `MarbleFramebuffer` source defines a 1125x2436 logical canvas over the 1080x2400 panel. It computes `fOffX=(1125-1080)/2=22` and `fOffY=(2436-2400)/2=18`, then subtracts those offsets from the destination when drawing. This is a centered crop at the panel edges, not an aspect-fit/letterbox transform. The inverse candidate for touch is therefore: divide the recovered 10x coordinates by 10 to get panel pixels, add `(22,18)` to get logical-canvas pixels, then divide by 3 for the iPhone X 375x812 point space. This is derived from source geometry only; the captured touches do not calibrate the edges, and no mapping code should be connected until the HID event range/coordinate contract is reviewed.

## Independent report decoder and current bridge gap

`goodix9916r_report_decoder.c` is a small independent parser for the report payload described by the pinned Ruby source. It validates the 8-byte report header and point-record additive checksums (sum of all preceding bytes modulo 65536, stored little-endian), then decodes count, ID nibble, and little-endian x/y/width fields. The matching source pins and recovered module SHA are in the source comments. Synthetic fixtures are in `test_goodix9916r_report_decoder.c`; they are not captured hardware packets. Host validation command:

```sh
clang -std=c11 -Wall -Wextra -Werror \
  goodix9916r_report_decoder.c test_goodix9916r_report_decoder.c \
  -o /tmp/goodix9916r-decoder-test && /tmp/goodix9916r-decoder-test
```

The synthetic fixture test passes under WSL Clang. This decoder handles payload parsing only; it has no SPI, MMIO, GPIO, regulator, reset, firmware-upload, or event-service code. Search of the local UniXNU/XNU trees found no Qualcomm GENI SPI controller driver. Therefore real XNU touch needs that controller/power/IRQ bridge plus the Goodix lifecycle before this parser can be connected to the existing IOHID event service. Linux Goodix source is GPL-2; this parser is an independent implementation of the published field/checksum description, and no GPL source has been copied into the APSL kernel tree.

## Verified recovery evidence and remaining XNU blocker

The recovery collector has already run successfully against serial `<redacted-device-serial>` and confirmed product `marble`. Its saved report is `research/hardware-goodix-recovery-20261025/goodix-recovery-readonly.json`; pulled firmware, config, and module files are in that same folder. The 15-second `/dev/input/event7` capture proves that the Android Goodix driver emits live, already-decoded touch events. The independent report decoder builds and passes its synthetic fixture test. These are verified collection/decoder results, not a working XNU touch driver.

The remaining blocker is the XNU hardware path: the local UniXNU/XNU trees have no Qualcomm GENI SPI controller driver, nor a completed Goodix power/reset/IRQ/firmware lifecycle that can read controller reports and publish IOHID events. The Android `goodix_core.ko` and GPL-2 source are protocol evidence only; they are not an APSL kernel port. The standalone decoder consumes report payloads only and has not been validated against captured raw SPI packets. Do not issue speculative SPI transactions or upload firmware.

`prepare_marble_goodix9916r_inventory.py` remains useful for a **host-side extracted** vendor/vendor_boot directory or a separately captured device, to locate and SHA-256 inventory the named blobs and candidate modules. It never uses ADB/USB and never writes to the phone. Example:

```powershell
python touch/prepare_marble_goodix9916r_inventory.py `
  --vendor-root D:\path\to\extracted-vendor `
  --json-out touch\vendor-inventory.json
```

The next engineering action is the legacy-XNU board adapter for the candidate
shared GENI SPI core, using the recovered exact board firmware/config and F5
power/pinctrl data. See [GENI-SPI-PROBE-PLAN.md](GENI-SPI-PROBE-PLAN.md) for the
bounded diagnostic prerequisites. No raw SPI probe or firmware flash has been
performed.

For an attached F5 already in ADB recovery, collect only the targeted evidence with an explicit serial:

```powershell
python touch/collect_marble_goodix_recovery.py --serial <adb-serial> --out touch\recovery-capture
```

The collector checks product properties when recovery exposes them, inventories already-present vendor trees without mounting, and pulls only exact-named firmware/config/module files to the host. It records `/proc/modules` and SPI/input sysfs bindings. If vendor trees are absent, it stops at that evidence; it does not mount them. A vendor_boot block read requires both `--pull-vendor-boot` and an explicit `--vendor-boot-block /dev/block/...`, streams only to a capped host file, and never supplies a remote output path.

