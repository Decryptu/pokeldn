/* The frame is vendor/LDN's AdvertisementFrame.encode, byte for byte; tests/test_esp32_beacon.py
   compares the two. docs/hardware_esp32.md, Portable beacon. */
#include "advert.h"

#include <stdbool.h>
#include <string.h>

/* Vendor-specific, Nintendo's OUI, LDN, advertisement 0x101, four zero bytes. */
static const uint8_t LDN_ADVERT_HEAD[12] = {0x7f, 0x00, 0x22, 0xaa, 0x04, 0x00, 0x01, 0x01, 0, 0, 0, 0};

static uint16_t le16(const uint8_t *p) { return (uint16_t)(p[0] | p[1] << 8); }

static uint32_t le32(const uint8_t *p)
{
    return (uint32_t)p[0] | (uint32_t)p[1] << 8 | (uint32_t)p[2] << 16 | (uint32_t)p[3] << 24;
}

uint32_t advert_crc32(const uint8_t *data, size_t length)
{
    uint32_t crc = 0xffffffffu;
    for (size_t i = 0; i < length; ++i) {
        crc ^= data[i];
        for (int bit = 0; bit < 8; ++bit) crc = (crc >> 1) ^ (0xedb88320u & -(crc & 1));
    }
    return ~crc;
}

int advert_parse(const uint8_t *data, size_t length, advert_image_t *image)
{
    if (length < 128 + 4 || length > ADVERT_IMAGE_MAX || le16(data + 6) != length) return 1;
    if (memcmp(data, ADVERT_MAGIC, 4) || data[4] != ADVERT_LAYOUT) return 2;
    if (data[5] != ADVERT_KIND_CYCLE && data[5] != ADVERT_KIND_HOST) return 3;
    if (le32(data + length - 4) != advert_crc32(data, length - 4)) return 4;
    memset(image, 0, sizeof(*image));
    image->channel = data[8];
    memcpy(image->bssid, data + 9, 6);
    memcpy(image->ssid, data + 15, 32);
    memcpy(image->data_key, data + 47, 16);
    image->max_stations = data[63];
    memcpy(image->advertise_key, data + 64, 16);
    memcpy(image->header, data + 80, ADVERT_HEADER_LEN);
    image->interval_ms = le16(data + 120);
    image->dwell_ms = le16(data + 122);
    image->count = data[124];
    image->display_count = data[125];
    image->kind = data[5];
    const uint8_t format = image->header[33];
    /* A host image builds its advertisements as stations join: no fragments, AES-GCM only. */
    const bool host = image->kind == ADVERT_KIND_HOST;
    if (image->channel < 1 || image->channel > 13 || (image->bssid[0] & 1) ||
        (host ? image->count || format != ADVERT_FORMAT_AES_GCM : !image->count) ||
        image->count > ADVERT_FRAGMENTS_MAX || image->display_count > ADVERT_DISPLAY_MAX ||
        image->interval_ms < 20 || image->interval_ms > 1000 || image->dwell_ms < image->interval_ms ||
        format < ADVERT_FORMAT_PLAIN || format > ADVERT_FORMAT_AES_GCM)
        return 5;
    const uint8_t *p = data + 128, *end = data + length - 4;
    for (unsigned i = 0; i < image->count; ++i) {
        if (end - p < 2) return 5;
        const uint16_t n = le16(p);
        if (!n || n > ADVERT_PLAIN_MAX || end - p - 2 < n) return 5;
        image->plain[i] = p + 2;
        image->plain_len[i] = n;
        p += 2 + n;
    }
    for (unsigned i = 0; i < image->display_count; ++i) {
        if (end - p < 2) return 5;
        const uint16_t n = le16(p);
        if (!n || n > 1024 || end - p - 2 < n) return 5;
        image->display[i] = p + 2;
        image->display_len[i] = n;
        p += 2 + n;
    }
    if (host) {
        image->records = p;
        image->records_len = (uint16_t)(end - p);
        return 0;
    }
    return p == end ? 0 : 5;
}

size_t advert_frame(const advert_image_t *image, unsigned index, uint32_t nonce,
                    const advert_crypto_t *crypto, uint8_t out[ADVERT_FRAME_MAX])
{
    if (index >= image->count) return 0;
    return advert_frame_plain(image, image->plain[index], image->plain_len[index], nonce, crypto, out);
}

size_t advert_frame_plain(const advert_image_t *image, const uint8_t *plain, size_t n, uint32_t nonce,
                          const advert_crypto_t *crypto, uint8_t out[ADVERT_FRAME_MAX])
{
    if (!n || n > ADVERT_PLAIN_MAX) return 0;
    memset(out, 0, 24);
    out[0] = 0xd0;                        /* management, action */
    memset(out + 4, 0xff, 6);
    memcpy(out + 10, image->bssid, 6);
    memset(out + 16, 0xff, 6);
    memcpy(out + 24, LDN_ADVERT_HEAD, sizeof(LDN_ADVERT_HEAD));
    uint8_t *header = out + 24 + sizeof(LDN_ADVERT_HEAD), *body = header + ADVERT_HEADER_LEN;
    memcpy(header, image->header, 34);
    header[34] = (uint8_t)(n >> 8);
    header[35] = (uint8_t)n;
    header[36] = (uint8_t)(nonce >> 24);
    header[37] = (uint8_t)(nonce >> 16);
    header[38] = (uint8_t)(nonce >> 8);
    header[39] = (uint8_t)nonce;
    const size_t head = 24 + sizeof(LDN_ADVERT_HEAD) + ADVERT_HEADER_LEN;
    if (header[33] == ADVERT_FORMAT_AES_GCM) {
        uint8_t iv[12] = {0};
        memcpy(iv, header + 36, 4);
        if (crypto->aes_gcm(image->advertise_key, iv, header, ADVERT_HEADER_LEN, plain, body + 16, n,
                            body))
            return 0;
        return head + 16 + n;
    }
    /* Plain and AES-CTR: SHA-256 over header, 32 zero bytes and payload goes in place of the zeros. */
    memset(body, 0, 32);
    memcpy(body + 32, plain, n);
    uint8_t digest[32];
    if (crypto->sha256(header, ADVERT_HEADER_LEN + 32 + n, digest)) return 0;
    memcpy(body, digest, 32);
    if (header[33] == ADVERT_FORMAT_AES_CTR) {
        uint8_t counter[16] = {0};
        memcpy(counter, header + 36, 4);
        if (crypto->aes_ctr(image->advertise_key, counter, body, body, 32 + n)) return 0;
    }
    return head + 32 + n;
}
