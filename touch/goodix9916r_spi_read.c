#include "goodix9916r_spi_read.h"

/* Matched BERLIN_D recovery module SHA256:
 * 096437302c7b81fe06a4ec1dfc793777d88a75cc5b06e3c3db8393a7f77aa372.
 * This independent framing helper is based on the ELF branch audit, not
 * copied from the GPL-2 driver. */
#include <stdint.h>

static int
ranges_overlap(const void *a, size_t a_len, const void *b, size_t b_len)
{
    uintptr_t a_start = (uintptr_t)a;
    uintptr_t b_start = (uintptr_t)b;

    /* Reject unrepresentable ranges rather than relying on wrapped ends. */
    if (a_len > UINTPTR_MAX - a_start || b_len > UINTPTR_MAX - b_start) {
        return 1;
    }
    return a_start < b_start + b_len && b_start < a_start + a_len;
}

goodix9916r_spi_read_status
goodix9916r_spi_read(goodix9916r_spi_transfer_fn transfer, void *context,
                     uint32_t address, size_t length, uint8_t *tx,
                     size_t tx_capacity, uint8_t *rx, size_t rx_capacity,
                     uint8_t *output, size_t output_capacity)
{
    size_t frame_length;
    size_t i;
    int transferred;

    if (transfer == NULL || tx == NULL || rx == NULL || output == NULL) {
        return GOODIX9916R_SPI_READ_BAD_ARGUMENT;
    }
    if (length == 0u || length > GOODIX9916R_SPI_READ_MAX_BYTES) {
        return GOODIX9916R_SPI_READ_BAD_LENGTH;
    }
    if ((uint64_t)address + (uint64_t)length - 1u > UINT32_MAX) {
        return GOODIX9916R_SPI_READ_ADDRESS_OVERFLOW;
    }
    frame_length = GOODIX9916R_SPI_READ_PREFIX_BYTES + length;
    if (tx_capacity < frame_length || rx_capacity < frame_length ||
        output_capacity < length) {
        return GOODIX9916R_SPI_READ_BAD_CAPACITY;
    }
    if (ranges_overlap(tx, frame_length, rx, frame_length) ||
        ranges_overlap(output, length, tx, frame_length) ||
        ranges_overlap(output, length, rx, frame_length)) {
        return GOODIX9916R_SPI_READ_ALIAS;
    }

    tx[0] = 0xf1u;
    tx[1] = (uint8_t)(address >> 24);
    tx[2] = (uint8_t)(address >> 16);
    tx[3] = (uint8_t)(address >> 8);
    tx[4] = (uint8_t)address;
    tx[5] = 0xffu;
    tx[6] = 0xffu;
    tx[7] = 0xffu;
    for (i = GOODIX9916R_SPI_READ_PREFIX_BYTES; i < frame_length; ++i) {
        tx[i] = 0xffu;
    }

    transferred = transfer(context, tx, rx, frame_length);
    if (transferred < 0) {
        return GOODIX9916R_SPI_READ_TRANSFER_FAILED;
    }
    if ((size_t)transferred != frame_length) {
        return GOODIX9916R_SPI_READ_SHORT_REPLY;
    }
    for (i = 0; i < length; ++i) {
        output[i] = rx[GOODIX9916R_SPI_READ_PREFIX_BYTES + i];
    }
    return GOODIX9916R_SPI_READ_OK;
}
