/* Independent implementation of the documented report layout; see header. */
#include "goodix9916r_report_decoder.h"

#include <string.h>

#define GOODIX_EVENT_TOUCH 0x80u

static uint16_t
read_le16(const uint8_t *p)
{
    return (uint16_t)((uint16_t)p[0] | ((uint16_t)p[1] << 8));
}

int
goodix9916r_checksum_valid(const uint8_t *data, size_t length)
{
    uint32_t sum = 0;
    size_t i;
    uint16_t stored;

    if (data == NULL || length < 2u) {
        return 0;
    }
    for (i = 0; i < length - 2u; ++i) {
        sum += data[i];
    }
    stored = read_le16(data + length - 2u);
    return (uint16_t)sum == stored;
}

goodix9916r_status
goodix9916r_decode_report(const uint8_t *data, size_t length,
                          goodix9916r_report *out)
{
    uint8_t count;
    size_t required;
    size_t i;
    uint16_t seen = 0;

    if (data == NULL || out == NULL) {
        return GOODIX9916R_BAD_ARGUMENT;
    }
    memset(out, 0, sizeof(*out));
    if (length < GOODIX9916R_HEADER_BYTES) {
        return GOODIX9916R_SHORT_HEADER;
    }
    if (!goodix9916r_checksum_valid(data, GOODIX9916R_HEADER_BYTES)) {
        return GOODIX9916R_BAD_HEADER_CHECKSUM;
    }
    out->event_status = data[0];
    if ((data[0] & GOODIX_EVENT_TOUCH) == 0u) {
        return GOODIX9916R_NOT_TOUCH_EVENT;
    }

    count = (uint8_t)(data[2] & 0x0fu);
    if (count > GOODIX9916R_MAX_CONTACTS) {
        return GOODIX9916R_TOO_MANY_CONTACTS;
    }
    out->touch_count = count;
    if (count == 0u) {
        return GOODIX9916R_OK;
    }

    required = GOODIX9916R_HEADER_BYTES +
               (size_t)count * GOODIX9916R_POINT_BYTES + 2u;
    if (length < required) {
        return GOODIX9916R_SHORT_POINTS;
    }
    if (!goodix9916r_checksum_valid(data + GOODIX9916R_HEADER_BYTES,
                                    (size_t)count * GOODIX9916R_POINT_BYTES + 2u)) {
        return GOODIX9916R_BAD_POINT_CHECKSUM;
    }

    for (i = 0; i < count; ++i) {
        const uint8_t *point = data + GOODIX9916R_HEADER_BYTES +
                               i * GOODIX9916R_POINT_BYTES;
        uint8_t id = (uint8_t)(point[0] >> 4);
        uint16_t bit;

        if (id >= GOODIX9916R_MAX_CONTACTS) {
            return GOODIX9916R_BAD_CONTACT_ID;
        }
        bit = (uint16_t)(1u << id);
        if ((seen & bit) != 0u) {
            return GOODIX9916R_DUPLICATE_CONTACT_ID;
        }
        seen = (uint16_t)(seen | bit);
        out->contacts[i].id = id;
        out->contacts[i].x = read_le16(point + 2u);
        out->contacts[i].y = read_le16(point + 4u);
        out->contacts[i].width = read_le16(point + 6u);
    }
    return GOODIX9916R_OK;
}
