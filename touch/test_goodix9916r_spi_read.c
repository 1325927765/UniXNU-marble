#include "goodix9916r_spi_read.h"

#include <assert.h>
#include <stdio.h>
#include <string.h>

typedef struct {
    int result;
    size_t calls;
} fake_context;

typedef struct {
    size_t expected_length;
    uint32_t expected_address;
    size_t calls;
} frame_context;

static int
fake_transfer(void *opaque, const uint8_t *tx, uint8_t *rx, size_t length)
{
    fake_context *context = (fake_context *)opaque;
    size_t i;
    static const uint8_t expected_prefix[8] = {
        0xf1u, 0x12u, 0x34u, 0x56u, 0x78u, 0xffu, 0xffu, 0xffu
    };
    ++context->calls;
    assert(length == 12u);
    assert(memcmp(tx, expected_prefix, sizeof(expected_prefix)) == 0);
    for (i = 8u; i < length; ++i) {
        assert(tx[i] == 0xffu);
        rx[i] = (uint8_t)(0xa0u + i - 8u);
    }
    for (i = 0; i < 8u; ++i) {
        rx[i] = 0x55u;
    }
    return context->result < 0 ? context->result : (int)length;
}

static int
short_transfer(void *opaque, const uint8_t *tx, uint8_t *rx, size_t length)
{
    fake_context *context = (fake_context *)opaque;
    (void)tx;
    memset(rx, 0xee, length);
    ++context->calls;
    return (int)length - 1;
}

static int
frame_transfer(void *opaque, const uint8_t *tx, uint8_t *rx, size_t length)
{
    frame_context *context = (frame_context *)opaque;
    size_t i;
    ++context->calls;
    assert(length == context->expected_length +
                       GOODIX9916R_SPI_READ_PREFIX_BYTES);
    assert(tx[0] == 0xf1u);
    assert(tx[1] == (uint8_t)(context->expected_address >> 24));
    assert(tx[2] == (uint8_t)(context->expected_address >> 16));
    assert(tx[3] == (uint8_t)(context->expected_address >> 8));
    assert(tx[4] == (uint8_t)context->expected_address);
    for (i = 5u; i < length; ++i) {
        assert(tx[i] == 0xffu);
    }
    memset(rx, 0x22, GOODIX9916R_SPI_READ_PREFIX_BYTES);
    for (i = 0; i < context->expected_length; ++i) {
        rx[GOODIX9916R_SPI_READ_PREFIX_BYTES + i] = (uint8_t)i;
    }
    return (int)length;
}

int
main(void)
{
    uint8_t tx[36], rx[36], output[28], expected_output[28];
    uint8_t overlap[48];
    fake_context context = {12, 0u};
    frame_context frame = {28u, 0x00010014u, 0u};
    goodix9916r_spi_read_status status;

    memset(output, 0x7c, sizeof(output));
    status = goodix9916r_spi_read(fake_transfer, &context, 0x12345678u, 4u,
                                  tx, sizeof(tx), rx, sizeof(rx), output,
                                  sizeof(output));
    assert(status == GOODIX9916R_SPI_READ_OK);
    assert(output[0] == 0xa0u && output[1] == 0xa1u &&
           output[2] == 0xa2u && output[3] == 0xa3u);

    memset(output, 0x7c, sizeof(output));
    memcpy(expected_output, output, sizeof(output));
    status = goodix9916r_spi_read(NULL, &context, 0u, 4u, tx, sizeof(tx), rx,
                                  sizeof(rx), output, sizeof(output));
    assert(status == GOODIX9916R_SPI_READ_BAD_ARGUMENT &&
           memcmp(output, expected_output, sizeof(output)) == 0 &&
           context.calls == 1u);
    status = goodix9916r_spi_read(fake_transfer, &context, 0u, 0u, tx,
                                  sizeof(tx), rx, sizeof(rx), output,
                                  sizeof(output));
    assert(status == GOODIX9916R_SPI_READ_BAD_LENGTH &&
           memcmp(output, expected_output, sizeof(output)) == 0 &&
           context.calls == 1u);
    status = goodix9916r_spi_read(fake_transfer, &context, 0u,
                                  GOODIX9916R_SPI_READ_MAX_BYTES + 1u, tx,
                                  sizeof(tx), rx, sizeof(rx), output,
                                  sizeof(output));
    assert(status == GOODIX9916R_SPI_READ_BAD_LENGTH &&
           memcmp(output, expected_output, sizeof(output)) == 0 &&
           context.calls == 1u);
    status = goodix9916r_spi_read(fake_transfer, &context, UINT32_MAX, 2u, tx,
                                  sizeof(tx), rx, sizeof(rx), output,
                                  sizeof(output));
    assert(status == GOODIX9916R_SPI_READ_ADDRESS_OVERFLOW &&
           memcmp(output, expected_output, sizeof(output)) == 0 &&
           context.calls == 1u);
    status = goodix9916r_spi_read(fake_transfer, &context, 0u, 4u, tx, 11u,
                                  rx, sizeof(rx), output, sizeof(output));
    assert(status == GOODIX9916R_SPI_READ_BAD_CAPACITY &&
           memcmp(output, expected_output, sizeof(output)) == 0 &&
           context.calls == 1u);
    status = goodix9916r_spi_read(fake_transfer, &context, 0u, 4u, tx,
                                  sizeof(tx), rx, 11u, output, sizeof(output));
    assert(status == GOODIX9916R_SPI_READ_BAD_CAPACITY &&
           memcmp(output, expected_output, sizeof(output)) == 0 &&
           context.calls == 1u);
    status = goodix9916r_spi_read(fake_transfer, &context, 0u, 4u, tx,
                                  sizeof(tx), rx, sizeof(rx), output, 3u);
    assert(status == GOODIX9916R_SPI_READ_BAD_CAPACITY &&
           memcmp(output, expected_output, sizeof(output)) == 0 &&
           context.calls == 1u);
    status = goodix9916r_spi_read(fake_transfer, &context, 0u, 4u, tx,
                                  sizeof(tx), tx, sizeof(tx), output,
                                  sizeof(output));
    assert(status == GOODIX9916R_SPI_READ_ALIAS &&
           memcmp(output, expected_output, sizeof(output)) == 0 &&
           context.calls == 1u);
    status = goodix9916r_spi_read(fake_transfer, &context, 0u, 4u, tx,
                                  sizeof(tx), rx, sizeof(rx), tx,
                                  sizeof(tx));
    assert(status == GOODIX9916R_SPI_READ_ALIAS &&
           memcmp(output, expected_output, sizeof(output)) == 0 &&
           context.calls == 1u);

    /* Partially overlapping TX/RX buffers are rejected as well. */
    status = goodix9916r_spi_read(fake_transfer, &context, 0u, 4u, overlap,
                                  sizeof(overlap), overlap + 4u,
                                  sizeof(overlap) - 4u, output, sizeof(output));
    assert(status == GOODIX9916R_SPI_READ_ALIAS &&
           memcmp(output, expected_output, sizeof(output)) == 0 &&
           context.calls == 1u);

    context.calls = 0u;
    status = goodix9916r_spi_read(short_transfer, &context, 0x12345678u, 4u,
                                  tx, sizeof(tx), rx, sizeof(rx), output,
                                  sizeof(output));
    assert(status == GOODIX9916R_SPI_READ_SHORT_REPLY &&
           memcmp(output, expected_output, sizeof(output)) == 0 &&
           context.calls == 1u);
    context.result = -1;
    status = goodix9916r_spi_read(fake_transfer, &context, 0x12345678u, 4u,
                                  tx, sizeof(tx), rx, sizeof(rx), output,
                                  sizeof(output));
    assert(status == GOODIX9916R_SPI_READ_TRANSFER_FAILED &&
           memcmp(output, expected_output, sizeof(output)) == 0);

    /* Actual Berlin_D version record fixture: register 0x10014, 28 bytes. */
    status = goodix9916r_spi_read(frame_transfer, &frame, 0x00010014u, 28u,
                                  tx, sizeof(tx), rx, sizeof(rx), output,
                                  sizeof(output));
    assert(status == GOODIX9916R_SPI_READ_OK && frame.calls == 1u);
    for (size_t i = 0; i < sizeof(output); ++i) {
        assert(output[i] == (uint8_t)i);
    }

    /* Last legal address with a one-byte read remains valid. */
    frame.expected_length = 1u;
    frame.expected_address = UINT32_MAX;
    frame.calls = 0u;
    status = goodix9916r_spi_read(frame_transfer, &frame, UINT32_MAX, 1u, tx,
                                  sizeof(tx), rx, sizeof(rx), output,
                                  sizeof(output));
    assert(status == GOODIX9916R_SPI_READ_OK && frame.calls == 1u &&
           output[0] == 0u);

    puts("Goodix 9916R BERLIN_D SPI read synthetic fixtures: PASS");
    return 0;
}
