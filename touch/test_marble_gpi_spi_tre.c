#include "marble_gpi_spi_tre.h"

#include <assert.h>
#include <stdio.h>
#include <string.h>

static marble_gpi_spi_tre_request
valid_request(void)
{
    marble_gpi_spi_tre_request request = {
        .tx_payload_iova = 0x123456789abc0800ULL,
        .rx_payload_iova = 0x0fedcba987654000ULL,
        .clock_source_index = 5u,
        .clock_source_count = 8u,
        .clock_divider = 8u,
        .chip_select = 0u,
        .transfer_length = MARBLE_GPI_VERSION_READ_BYTES,
        .context_verified = 1u
    };
    return request;
}

static void
assert_tre(const marble_gpi_tre *tre, uint32_t d0, uint32_t d1,
           uint32_t d2, uint32_t d3)
{
    assert(tre->dword[0] == d0);
    assert(tre->dword[1] == d1);
    assert(tre->dword[2] == d2);
    assert(tre->dword[3] == d3);
}

static void
assert_unchanged(const marble_gpi_tre *tx, const marble_gpi_tre *rx,
                 const marble_gpi_tre *tx_before,
                 const marble_gpi_tre *rx_before)
{
    assert(memcmp(tx, tx_before, MARBLE_GPI_TX_TRE_COUNT * sizeof(*tx)) == 0);
    assert(memcmp(rx, rx_before, MARBLE_GPI_RX_TRE_COUNT * sizeof(*rx)) == 0);
}

static marble_gpi_spi_tre_status
expect_failure(marble_gpi_spi_tre_request request,
               marble_gpi_tre *tx, size_t tx_cap,
               marble_gpi_tre *rx, size_t rx_cap)
{
    marble_gpi_tre tx_before[MARBLE_GPI_TX_TRE_COUNT];
    marble_gpi_tre rx_before[MARBLE_GPI_RX_TRE_COUNT];
    memcpy(tx_before, tx, sizeof(tx_before));
    memcpy(rx_before, rx, sizeof(rx_before));
    marble_gpi_spi_tre_status status = marble_gpi_spi_build_version_read_tres(
        &request, tx, tx_cap, rx, rx_cap);
    assert_unchanged(tx, rx, tx_before, rx_before);
    return status;
}

int
main(void)
{
    marble_gpi_tre tx[MARBLE_GPI_TX_TRE_COUNT];
    marble_gpi_tre rx[MARBLE_GPI_RX_TRE_COUNT];
    marble_gpi_spi_tre_request request = valid_request();
    marble_gpi_spi_tre_status status;

    memset(tx, 0xa5, sizeof(tx));
    memset(rx, 0x5a, sizeof(rx));
    status = marble_gpi_spi_build_version_read_tres(
        &request, tx, MARBLE_GPI_TX_TRE_COUNT, rx, MARBLE_GPI_RX_TRE_COUNT);
    assert(status == MARBLE_GPI_SPI_TRE_OK);

    /* Golden values from the pinned numeric format: CONFIG0, GO, TX DMA;
     * the GO RX link points at the independent RX ring's one buffer TRE. */
    assert_tre(&tx[0], 0x03000004u, 0u, 0x00050008u, 0x00220001u);
    assert_tre(&tx[1], 0x00000003u, 0u, 36u, 0x00200801u);
    assert_tre(&tx[2], 0x9abc0800u, 0x12345678u, 36u, 0x00100200u);
    assert_tre(&rx[0], 0x87654000u, 0x0fedcba9u, 36u, 0x00100000u);

    request.context_verified = 0u;
    assert(expect_failure(request, tx, 3u, rx, 1u) ==
           MARBLE_GPI_SPI_TRE_UNVERIFIED_CONTEXT);
    request = valid_request();
    request.transfer_length = 35u;
    assert(expect_failure(request, tx, 3u, rx, 1u) ==
           MARBLE_GPI_SPI_TRE_BAD_LENGTH);
    request = valid_request();
    request.chip_select = 1u;
    assert(expect_failure(request, tx, 3u, rx, 1u) ==
           MARBLE_GPI_SPI_TRE_BAD_CHIP_SELECT);
    request = valid_request();
    request.clock_source_index = 8u;
    assert(expect_failure(request, tx, 3u, rx, 1u) ==
           MARBLE_GPI_SPI_TRE_BAD_CLOCK);
    request = valid_request();
    request.clock_source_count = 5u;
    assert(expect_failure(request, tx, 3u, rx, 1u) ==
           MARBLE_GPI_SPI_TRE_BAD_CLOCK);
    request = valid_request();
    request.clock_divider = 0u;
    assert(expect_failure(request, tx, 3u, rx, 1u) ==
           MARBLE_GPI_SPI_TRE_BAD_CLOCK);
    request.clock_divider = 0x1000u;
    assert(expect_failure(request, tx, 3u, rx, 1u) ==
           MARBLE_GPI_SPI_TRE_BAD_CLOCK);
    request = valid_request();
    request.tx_payload_iova = UINT64_MAX - 34u;
    assert(expect_failure(request, tx, 3u, rx, 1u) ==
           MARBLE_GPI_SPI_TRE_IOVA_OVERFLOW);
    request = valid_request();
    request.rx_payload_iova = request.tx_payload_iova + 35u;
    assert(expect_failure(request, tx, 3u, rx, 1u) ==
           MARBLE_GPI_SPI_TRE_IOVA_ALIAS);
    request = valid_request();
    assert(expect_failure(request, tx, 2u, rx, 1u) ==
           MARBLE_GPI_SPI_TRE_BAD_CAPACITY);
    assert(expect_failure(request, tx, 3u, rx, 0u) ==
           MARBLE_GPI_SPI_TRE_BAD_CAPACITY);

    request = valid_request();
    request.clock_source_index = 7u;
    request.clock_source_count = 8u;
    request.clock_divider = 0x0fffu;
    assert(marble_gpi_spi_build_version_read_tres(
               &request, tx, 3u, rx, 1u) == MARBLE_GPI_SPI_TRE_OK);
    assert(tx[0].dword[2] == 0x00070fffu);

    request = valid_request();
    marble_gpi_tre alias_before[MARBLE_GPI_TX_TRE_COUNT];
    memcpy(alias_before, tx, sizeof(alias_before));
    assert(marble_gpi_spi_build_version_read_tres(
               &request, tx, 3u, (marble_gpi_tre *)tx, 1u) ==
           MARBLE_GPI_SPI_TRE_OUTPUT_ALIAS);
    assert(memcmp(alias_before, tx, sizeof(alias_before)) == 0);

    request.tx_payload_iova = UINT64_MAX - 35u;
    request.rx_payload_iova = 0x4000u;
    assert(marble_gpi_spi_build_version_read_tres(
               &request, tx, 3u, rx, 1u) == MARBLE_GPI_SPI_TRE_OK);
    assert(tx[2].dword[0] == 0xffffffdcu && tx[2].dword[1] == UINT32_MAX);

    /* The selected setup path declares no payload-IOVA alignment check. */
    request.tx_payload_iova = 0x1001u;
    request.rx_payload_iova = 0x2002u;
    assert(marble_gpi_spi_build_version_read_tres(
               &request, tx, 3u, rx, 1u) == MARBLE_GPI_SPI_TRE_OK);
    assert(tx[2].dword[0] == 0x1001u && rx[0].dword[0] == 0x2002u);

    puts("Marble GPI SPI version-read TRE fixtures: PASS");
    return 0;
}
