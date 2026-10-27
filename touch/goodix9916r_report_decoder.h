/*
 * Independent, source-derived parser for the Goodix 9916R report payload.
 * This file is not copied from the GPL-2 Linux driver and contains no SPI I/O.
 * Provenance: MiCode/Xiaomi_Kernel_OpenSource ruby-s-oss commit
 * 914ba8403bb3a957ed37b99dcecdbafce9d16121; goodix_brl_hw.c SHA256
 * 4f832cff7f7d2947ae47a3131edb3f5d6dc3470e883da05538f8a7b44b8fda68.
 * Local matched recovery module SHA256:
 * 096437302c7b81fe06a4ec1dfc793777d88a75cc5b06e3c3db8393a7f77aa372.
 */
#ifndef GOODIX9916R_REPORT_DECODER_H
#define GOODIX9916R_REPORT_DECODER_H

#include <stddef.h>
#include <stdint.h>

#define GOODIX9916R_MAX_CONTACTS 10u
#define GOODIX9916R_HEADER_BYTES 8u
#define GOODIX9916R_POINT_BYTES 8u

typedef enum {
    GOODIX9916R_OK = 0,
    GOODIX9916R_NOT_TOUCH_EVENT,
    GOODIX9916R_BAD_ARGUMENT,
    GOODIX9916R_SHORT_HEADER,
    GOODIX9916R_BAD_HEADER_CHECKSUM,
    GOODIX9916R_TOO_MANY_CONTACTS,
    GOODIX9916R_SHORT_POINTS,
    GOODIX9916R_BAD_POINT_CHECKSUM,
    GOODIX9916R_BAD_CONTACT_ID,
    GOODIX9916R_DUPLICATE_CONTACT_ID
} goodix9916r_status;

typedef struct {
    uint8_t id;
    uint16_t x;
    uint16_t y;
    uint16_t width;
} goodix9916r_contact;

typedef struct {
    uint8_t event_status;
    uint8_t touch_count;
    goodix9916r_contact contacts[GOODIX9916R_MAX_CONTACTS];
} goodix9916r_report;

/* Input is the controller's event payload beginning at its report header,
 * after the transport layer has completed a register read. No SPI framing,
 * reset, power, or firmware upload is implemented here. */
goodix9916r_status goodix9916r_decode_report(const uint8_t *data, size_t length,
                                               goodix9916r_report *out);

/* Exposed for fixture generation/validation. `length` includes the final
 * two checksum bytes; preceding bytes are summed modulo 65536, little-endian. */
int goodix9916r_checksum_valid(const uint8_t *data, size_t length);

#endif
