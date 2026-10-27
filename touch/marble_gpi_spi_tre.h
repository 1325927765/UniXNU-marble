/*
 * Independent host-side TRE builder for one bounded Goodix version read.
 * Source facts: MiCode Xiaomi_Kernel_OpenSource marble-s-oss HEAD
 * 48952ed36228217531482b39d5bef13e7fd808ec, drivers/spi/spi-msm-geni.c;
 * include/linux/msm_gpi.h; include/linux/msm-geni-se.h.
 * No GPL implementation function or macro is copied here.
 */
#ifndef MARBLE_GPI_SPI_TRE_H
#define MARBLE_GPI_SPI_TRE_H

#include <stddef.h>
#include <stdint.h>

#define MARBLE_GPI_TRE_DWORDS 4u
#define MARBLE_GPI_TRE_BYTES 16u
#define MARBLE_GPI_VERSION_READ_BYTES 36u
#define MARBLE_GPI_TX_TRE_COUNT 3u
#define MARBLE_GPI_RX_TRE_COUNT 1u

typedef struct {
    uint32_t dword[MARBLE_GPI_TRE_DWORDS];
} marble_gpi_tre;

typedef struct {
    /* Caller asserts these IOVAs are valid for this verified controller. */
    uint64_t tx_payload_iova;
    uint64_t rx_payload_iova;
    /* Source-clock selection and divider already resolved by the provider. */
    uint32_t clock_source_index;
    uint32_t clock_source_count;
    uint16_t clock_divider;
    uint8_t chip_select;
    uint32_t transfer_length;
    /* Must be set only after the controller/ring context has been verified. */
    uint8_t context_verified;
} marble_gpi_spi_tre_request;

typedef enum {
    MARBLE_GPI_SPI_TRE_OK = 0,
    MARBLE_GPI_SPI_TRE_BAD_ARGUMENT,
    MARBLE_GPI_SPI_TRE_UNVERIFIED_CONTEXT,
    MARBLE_GPI_SPI_TRE_BAD_LENGTH,
    MARBLE_GPI_SPI_TRE_BAD_CHIP_SELECT,
    MARBLE_GPI_SPI_TRE_BAD_CLOCK,
    MARBLE_GPI_SPI_TRE_IOVA_OVERFLOW,
    MARBLE_GPI_SPI_TRE_IOVA_ALIAS,
    MARBLE_GPI_SPI_TRE_BAD_CAPACITY,
    MARBLE_GPI_SPI_TRE_OUTPUT_ALIAS
} marble_gpi_spi_tre_status;

/* Build CONFIG0 + GO + TX buffer TREs and one RX buffer TRE for a single
 * 36-byte full-duplex command on chip select 0. Inputs are caller-verified
 * DMA IOVAs, not CPU pointers or ring addresses. The builder performs no DMA,
 * mapping, MMIO, clock lookup, or controller access. Output arrays are left
 * unchanged on all validation failures. `context_verified` is an explicit
 * gate; it does not establish that hardware state has actually been checked.
 * The caller supplies the valid clock table count because the source driver
 * obtains this index from the SE performance table; the serialized field is
 * 16 bits. No payload-IOVA alignment restriction is imposed here: the cited
 * TRE setup code does not encode one, so the provider remains responsible for
 * controller/DMA-specific address validity.
 *
 * The four words are numeric uint32_t descriptor values. A future ARM64
 * provider must serialize them in the controller's little-endian format,
 * place them into appropriately aligned ring storage, and handle cache and
 * coherency itself.
 */
marble_gpi_spi_tre_status marble_gpi_spi_build_version_read_tres(
    const marble_gpi_spi_tre_request *request,
    marble_gpi_tre *tx_ring_entries, size_t tx_capacity,
    marble_gpi_tre *rx_ring_entries, size_t rx_capacity);

#endif
