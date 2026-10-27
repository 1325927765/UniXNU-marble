/*
 * Independent BERLIN_D register-read framing helper. This is not copied from
 * the GPL-2 Linux driver and does not access hardware itself.
 */
#ifndef GOODIX9916R_SPI_READ_H
#define GOODIX9916R_SPI_READ_H

#include <stddef.h>
#include <stdint.h>

/* Small diagnostic bound; this helper is not intended for bulk transfers. */
#define GOODIX9916R_SPI_READ_MAX_BYTES 256u
#define GOODIX9916R_SPI_READ_PREFIX_BYTES 8u

typedef enum {
    GOODIX9916R_SPI_READ_OK = 0,
    GOODIX9916R_SPI_READ_BAD_ARGUMENT,
    GOODIX9916R_SPI_READ_BAD_CAPACITY,
    GOODIX9916R_SPI_READ_BAD_LENGTH,
    GOODIX9916R_SPI_READ_ADDRESS_OVERFLOW,
    GOODIX9916R_SPI_READ_ALIAS,
    GOODIX9916R_SPI_READ_TRANSFER_FAILED,
    GOODIX9916R_SPI_READ_SHORT_REPLY
} goodix9916r_spi_read_status;

/* Callback clocks exactly one full-duplex transaction and returns the number
 * of bytes transferred, or a negative value on failure. It must access no
 * more than `length` bytes in either buffer and treat tx as read-only. The
 * helper itself does not modify context or output before full success. */
typedef int (*goodix9916r_spi_transfer_fn)(void *context, const uint8_t *tx,
                                           uint8_t *rx, size_t length);

/* Perform a bounded read using caller-owned buffers. The frame is
 * F1 + BE32(address) + FF FF FF + `length` dummy bytes. FF is a host-side
 * dummy-byte policy based on the identified framing; no bus waveform has
 * been captured to verify the transmitted dummy values. Payload is copied
 * from RX offset 8 only after a complete callback transfer. Output is left
 * unchanged for every validation or transfer failure. This routine performs
 * no SPI/MMIO access except through the supplied callback, and does not
 * initialize, reset, write, or upload firmware to the controller. */
goodix9916r_spi_read_status goodix9916r_spi_read(
    goodix9916r_spi_transfer_fn transfer, void *context, uint32_t address,
    size_t length, uint8_t *tx, size_t tx_capacity, uint8_t *rx,
    size_t rx_capacity, uint8_t *output, size_t output_capacity);

#endif
