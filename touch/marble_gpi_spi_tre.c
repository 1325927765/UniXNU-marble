#include "marble_gpi_spi_tre.h"

#include <string.h>

/* Independent numeric field definitions derived from the cited source.
 * CONFIG0 packs TX/RX (1|2), uses bpw-4 for word-size, and chains onward.
 * Full-duplex GO (opcode 3) links RX (opcode has RX bit 2 set), has zero EOT
 * and EOB, and chains. The TX DMA buffer sets IEOT; RX does not. */
enum {
    GPI_RING_TYPE_DMA = 1u,
    GPI_RING_TYPE_SPI = 2u,
    GPI_SPI_TRE_CONFIG0 = 2u,
    SPI_COMMAND_FULL_DUPLEX = 3u,
    SPI_PACK_TX_RX = 3u,
    SPI_WORD_SIZE_8_BIT = 8u - 4u,
    CLOCK_INDEX_FIELD_MAX = 0xffffu,
    CLOCK_DIVIDER_MAX = 0x0fffu
};

_Static_assert(sizeof(marble_gpi_tre) == MARBLE_GPI_TRE_BYTES,
               "GPI TRE must contain exactly four 32-bit words");

static int
io_ranges_overlap(uint64_t a, uint64_t b, uint64_t length)
{
    return a <= b ? b - a < length : a - b < length;
}

static int
memory_ranges_overlap(const void *a, size_t a_len, const void *b, size_t b_len)
{
    uintptr_t a_start = (uintptr_t)a;
    uintptr_t b_start = (uintptr_t)b;

    if (a_len > UINTPTR_MAX - a_start || b_len > UINTPTR_MAX - b_start) {
        return 1;
    }
    return a_start < b_start + b_len && b_start < a_start + a_len;
}

static void
set_dma_tre(marble_gpi_tre *tre, uint64_t iova, uint32_t is_tx)
{
    tre->dword[0] = (uint32_t)iova;
    tre->dword[1] = (uint32_t)(iova >> 32);
    tre->dword[2] = MARBLE_GPI_VERSION_READ_BYTES;
    /* Type=DMA buffer; TX alone requests IEOT. No IEOB or chaining. */
    tre->dword[3] = (GPI_RING_TYPE_DMA << 20) | (is_tx << 9);
}

marble_gpi_spi_tre_status
marble_gpi_spi_build_version_read_tres(const marble_gpi_spi_tre_request *input,
                                       marble_gpi_tre *tx_ring_entries,
                                       size_t tx_capacity,
                                       marble_gpi_tre *rx_ring_entries,
                                       size_t rx_capacity)
{
    marble_gpi_spi_tre_request request;
    marble_gpi_tre tx[MARBLE_GPI_TX_TRE_COUNT];
    marble_gpi_tre rx[MARBLE_GPI_RX_TRE_COUNT];
    uint64_t last_offset = MARBLE_GPI_VERSION_READ_BYTES - 1u;

    if (input == NULL || tx_ring_entries == NULL || rx_ring_entries == NULL) {
        return MARBLE_GPI_SPI_TRE_BAD_ARGUMENT;
    }
    request = *input;
    if (request.context_verified != 1u) {
        return MARBLE_GPI_SPI_TRE_UNVERIFIED_CONTEXT;
    }
    if (request.transfer_length != MARBLE_GPI_VERSION_READ_BYTES) {
        return MARBLE_GPI_SPI_TRE_BAD_LENGTH;
    }
    if (request.chip_select != 0u) {
        return MARBLE_GPI_SPI_TRE_BAD_CHIP_SELECT;
    }
    if (request.clock_source_count == 0u ||
        request.clock_source_count > CLOCK_INDEX_FIELD_MAX + 1u ||
        request.clock_source_index >= request.clock_source_count ||
        request.clock_source_index > CLOCK_INDEX_FIELD_MAX ||
        request.clock_divider == 0u || request.clock_divider > CLOCK_DIVIDER_MAX) {
        return MARBLE_GPI_SPI_TRE_BAD_CLOCK;
    }
    if (request.tx_payload_iova > UINT64_MAX - last_offset ||
        request.rx_payload_iova > UINT64_MAX - last_offset) {
        return MARBLE_GPI_SPI_TRE_IOVA_OVERFLOW;
    }
    if (io_ranges_overlap(request.tx_payload_iova, request.rx_payload_iova,
                          MARBLE_GPI_VERSION_READ_BYTES)) {
        return MARBLE_GPI_SPI_TRE_IOVA_ALIAS;
    }
    if (tx_capacity < MARBLE_GPI_TX_TRE_COUNT ||
        rx_capacity < MARBLE_GPI_RX_TRE_COUNT) {
        return MARBLE_GPI_SPI_TRE_BAD_CAPACITY;
    }
    if (memory_ranges_overlap(tx_ring_entries,
                              MARBLE_GPI_TX_TRE_COUNT * sizeof(*tx_ring_entries),
                              rx_ring_entries,
                              MARBLE_GPI_RX_TRE_COUNT * sizeof(*rx_ring_entries))) {
        return MARBLE_GPI_SPI_TRE_OUTPUT_ALIAS;
    }

    memset(tx, 0, sizeof(tx));
    memset(rx, 0, sizeof(rx));
    /* CONFIG0: pack TX/RX, mode-0 flags, 8-bit words; sourced clock fields. */
    tx[0].dword[0] = (SPI_PACK_TX_RX << 24) | SPI_WORD_SIZE_8_BIT;
    tx[0].dword[2] = ((uint32_t)request.clock_source_index << 16) |
                     request.clock_divider;
    /* CONFIG0 TRE type with chain=1 to the following GO TRE. */
    tx[0].dword[3] = (GPI_RING_TYPE_SPI << 20) |
                     (GPI_SPI_TRE_CONFIG0 << 16) | 1u;

    /* One full-duplex GO for CS0 and RX count 36; chain into TX DMA. */
    tx[1].dword[0] = SPI_COMMAND_FULL_DUPLEX;
    tx[1].dword[2] = MARBLE_GPI_VERSION_READ_BYTES;
    tx[1].dword[3] = (GPI_RING_TYPE_SPI << 20) | (1u << 11) | 1u;

    set_dma_tre(&tx[2], request.tx_payload_iova, 1u);
    set_dma_tre(&rx[0], request.rx_payload_iova, 0u);
    memcpy(tx_ring_entries, tx, sizeof(tx));
    memcpy(rx_ring_entries, rx, sizeof(rx));
    return MARBLE_GPI_SPI_TRE_OK;
}
