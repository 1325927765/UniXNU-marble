# Marble SMMUv2 stream snapshot decoder

This host-only helper decodes already captured Stream Mapping Register (SMR) and Stream-to-Context Register (S2CR) words. It performs no MMIO, DMA, SMMU mutation, or bypass. A caller must separately verify the SMMU format from IDR0 and pass the corresponding explicit format; the helper will reject unverified or unspecified formats.

## Register facts and provenance

Source is the locally downloaded Marble kernel at commit `48952ed36228217531482b39d5bef13e7fd808ec` (Xiaomi Marble kernel, 2023-06-02). The relevant definitions are in `drivers/iommu/arm/arm-smmu/arm-smmu.h`: IDR0 EXIDS is bit 8; SMR ID is bits 15:0, mask is bits 31:16, and legacy VALID is bit 31; S2CR TYPE is bits 17:16, CBNDX bits 7:0, EXIDVALID bit 10. `arm-smmu.c` feature detection sets `ARM_SMMU_FEAT_EXIDS` from `IDR0_EXIDS` (around line 3630). In its snapshot initialization (around lines 3454–3500), Marble extracts validity from S2CR.EXIDVALID when EXIDS is active; without EXIDS it extracts SMR.VALID and clears that bit before reading the legacy mask (where mask bits 30:16 are usable). `arm-smmu-qcom.c` also reads type and CBNDX from S2CR in its Qualcomm snapshot path (around lines 36–60). The route encodings are TRANS=0, BYPASS=1, FAULT=2; encoding 3 is reported as invalid.

The matching relation treats mask bits as don't-care SID bits. More than one valid matching SME returns `AMBIGUOUS` and no context bank is selected. The supported entry limit is 128 as requested for this narrow Marble snapshot tool; this is a caller bound, not a claim that every SMMUv2 instance has 128 entries.

## Marble DTS context

The saved live DTS `research/hardware-live-20261023-connected/marble-live.dts` identifies wrapper context SID `0x5a3` at the `qcom,qupv3_0_geni_se@9c0000` node (lines 12410–12422) and GPI engine SID `0x5b6` at `qcom,gpi-dma@900000` (lines 12425–12440). Its apps-SMMU node sets `qcom,num-smr-override = <0x78>` (120 entries, line 18569); the decoder's 128-entry bound is a requested safety cap, not the universal or DTS-reported count. The decoder can classify entries matching either SID once the caller supplies corresponding register snapshots. A route of `TRANSLATE` only reports the S2CR's context-bank index; it does not validate that bank's CBAR/CBA2R configuration, page tables, stream/TBU connectivity, permission bits, or whether the wrapper and GPI stream use compatible mappings. It is a readout interpreter, not an authorization to DMA.

## Limits

- No IDR0, SMR, S2CR, CBAR, context-bank, TBU, or fault-register values have been read by this helper.
- The caller must cap snapshots to 128 entries and ensure each SMR and S2CR array entry refers to the same index.
- EXIDS format must be confirmed from the actual SMMU's IDR0 bit 8 before passing `MARBLE_SMMU_FORMAT_EXIDS`; this library contains no MMIO code and cannot verify that fact itself.
- A unique matching translation route does not establish that DMA is safe. Do not program DMA, alter stream mappings, or bypass the IOMMU based on this decoder result alone.
