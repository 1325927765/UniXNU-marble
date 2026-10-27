# Marble touch DMA path

Local engineering note, 2026-10-25. No GPI command or touch-controller
transaction has been issued by the XNU port. This unfinished work is not part
of the public documentation-only community repository.

## Why the current shared SPI core is insufficient

The observed GENI SE IF_DISABLE value is 1 (FIFO disabled). In pinned Xiaomi
Marble source `48952ed36228217531482b39d5bef13e7fd808ec`,
`drivers/spi/spi-msm-geni.c::select_xfer_mode()` chooses GSI_DMA when FIFO is
disabled and both GPI channels exist; otherwise it fails. Its SE_DMA route is
selected when FIFO is enabled. The `QcomGeniSpi` SE-DMA implementation therefore
does not establish a valid fallback on this observed device state.

## Source-backed topology

| Role | Source-defined resource | Required mapping |
| --- | --- | --- |
| SPI SE4 | `0x990000`, Goodix CS0, maximum 15 MHz | Controller MMIO, reviewed clocks and pins |
| GPI engine | `0x900000`, size `0x60000`, EE offset `0x10000` | GPI ring allocations through its own DMA context |
| GPI stream | apps-SMMU SID `0x5b6`, pool `0x100000/0x100000` | Transfer/event ring addresses must be valid for this stream |
| QUP wrapper | `0x9c0000`, SID `0x5a3`, pool `0x40000000/0x10000000` | Payload mappings follow the wrapper DMA context |
| SPI DMA channels | TX0 / RX1, SEID4, protocol1, 64 TREs, final DT cell2 | That final cell decodes to static GPII0, not an arbitrary dynamic channel |

The DTS source is `research/hardware-live-20261023-connected/marble-live.dts`,
wrapper/GPI nodes around lines 12410-12440 and SPI node around line 12628.
The applicable Linux files are read with `git show` from the sparse local
Marble source checkout. `geni_se_iommu_map_buf()` maps payload buffers through
the wrapper context; GPI allocates coherent rings through its own device.
Do not substitute physical addresses or a mapping for only one stream.

## Concrete implementation boundary

The Linux GPI path needs paired TX/RX rings, an event ring, channel and event
allocation/start commands, doorbells and completion/error handling. Its TREs
are 16 bytes (four dwords); the relevant SPI types include CONFIG0 `0x22`,
GO `0x20` and DMA_W_BUF `0x10`. For the declared 64-entry TX/RX rings, Linux's
event sizing rule produces 256 event entries. These source facts are not a
validated XNU ring implementation.

Before running the first 36-byte Goodix version transaction, establish both
DMA contexts and lifetimes, ownership of static GPII0, event completion and
timeout/quiesce behavior, and the exact pin/power state. Existing UFS DMA
success concerns a different stream and does not prove either touch path.
No retained UEFI GPI ring state has been captured; do not adopt firmware
rings or change SMMU stream routes on that assumption.

## Recovery binding observations

Read-only collection after video `20261025_214554.mp4` confirms:

- `900000.qcom,gpi-dma` is bound to `gpi_dma`, IOMMU group 8, type `DMA`.
  Its reserved-region list leaves the configured 1–2 MiB IOVA pool.
- `9c0000.qcom,qupv3_0_geni_se` is bound to `qupv3_geni_se`, IOMMU group 1,
  type `unmanaged`. Its reserved-region list leaves the configured
  `0x40000000..0x50000000` IOVA window. Here `unmanaged` is the Linux IOMMU
  domain type; it does not mean bypass or absence of translation.
- The SPI device itself has no IOMMU-group link.
- The read-only DMAengine summary identifies `dma1chan0` as `990000.spi:tx`
  and `dma1chan1` as `990000.spi:rx` on the 900000 GPI controller. This
  confirms the live Linux channel association, not XNU GPI ownership.

The private captures are `dma-bindings-before-debugfs.json`,
`dma-bindings-debugfs-readonly.json` and `dmaengine-summary-readonly.json`
under the existing Goodix Recovery evidence directory. Only debugfs was
temporarily mounted read-only for the latter reads, then unmounted. No DMA
commands, sysfs writes, raw MMIO or SMMU programming occurred.

These observations do not reveal current SMR/S2CR register values, page-table
contents, or a reusable UEFI mapping. The two roles must remain distinct in
the future XNU provider.

`marble_smmu_stream.{c,h}` is a host-tested decoder for already-read SMR/S2CR
words, not an IOMMU driver. It rejects ambiguous or unverified format inputs
and makes no MMIO, DMA or SMMU changes. It will help interpret a bounded
readout once the corresponding hardware format is established.

`marble_gpi_spi_tre.{c,h}` now builds the numeric CONFIG0, full-duplex GO, TX
and RX buffer TRE words for a bounded 36-byte transfer. It requires explicit
caller-verified payload IOVAs and clock selection, rejects invalid fields and
overlapping buffers, and leaves outputs unchanged on validation failure.
Golden-word and boundary fixtures pass under Clang with ASan/UBSan. It does
not allocate DMA memory, map either stream, own a channel, ring a doorbell or
process completion events, and is not yet integrated into XNU.

The next hardware checkpoint is a bounded read-only snapshot of the retained
apps-SMMU stream routing for `0x5a3`/`0x5b6`, relevant context configuration,
GPII0 channel/event state and exact TLMM pin state. Derive any snapshot offsets
and access prerequisites from the pinned source; do not start DMA or adopt
retained rings from a match result alone. Only after that ownership/mapping
boundary is established can the provider safely connect these descriptors
to the existing SPI framing helper and version-response validation.
