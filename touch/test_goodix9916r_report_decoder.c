/* Synthetic fixtures for the independent source-derived payload decoder. */
#include "goodix9916r_report_decoder.h"

#include <assert.h>
#include <stdio.h>
#include <string.h>

static void
append_sum16_le(uint8_t *p, size_t data_length)
{
    uint32_t sum = 0;
    size_t i;
    for (i = 0; i < data_length; ++i) {
        sum += p[i];
    }
    p[data_length] = (uint8_t)sum;
    p[data_length + 1u] = (uint8_t)(sum >> 8);
}

static void
put_le16(uint8_t *p, uint16_t value)
{
    p[0] = (uint8_t)value;
    p[1] = (uint8_t)(value >> 8);
}

static void
make_one_contact(uint8_t *packet)
{
    memset(packet, 0, 18u);
    packet[0] = 0x80; /* touch-event bit */
    packet[2] = 1;    /* one contact */
    append_sum16_le(packet, 6u); /* 8-byte header checksum */
    packet[8] = 0x20; /* contact ID 2 in high nibble */
    put_le16(packet + 10u, 1080u);
    put_le16(packet + 12u, 2400u);
    put_le16(packet + 14u, 31u);
    append_sum16_le(packet + 8u, 8u);
}

int
main(void)
{
    uint8_t packet[26];
    goodix9916r_report report;

    make_one_contact(packet);
    assert(goodix9916r_decode_report(packet, 18u, &report) == GOODIX9916R_OK);
    assert(report.event_status == 0x80u && report.touch_count == 1u);
    assert(report.contacts[0].id == 2u);
    assert(report.contacts[0].x == 1080u && report.contacts[0].y == 2400u);
    assert(report.contacts[0].width == 31u);

    packet[7] ^= 1u;
    assert(goodix9916r_decode_report(packet, 18u, &report) ==
           GOODIX9916R_BAD_HEADER_CHECKSUM);
    make_one_contact(packet);
    packet[15] ^= 1u;
    assert(goodix9916r_decode_report(packet, 18u, &report) ==
           GOODIX9916R_BAD_POINT_CHECKSUM);

    make_one_contact(packet);
    packet[2] = 11u;
    append_sum16_le(packet, 6u);
    assert(goodix9916r_decode_report(packet, 18u, &report) ==
           GOODIX9916R_TOO_MANY_CONTACTS);

    make_one_contact(packet);
    packet[8] = 0xf0;
    append_sum16_le(packet + 8u, 8u);
    assert(goodix9916r_decode_report(packet, 18u, &report) ==
           GOODIX9916R_BAD_CONTACT_ID);

    make_one_contact(packet);
    assert(goodix9916r_decode_report(packet, 17u, &report) ==
           GOODIX9916R_SHORT_POINTS);

    puts("Goodix 9916R report decoder synthetic fixtures: PASS");
    return 0;
}
