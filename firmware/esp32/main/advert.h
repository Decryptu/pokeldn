/* A stored LDN advertisement cycle: the image the host writes with CMD_BEACON and the action frames
   the board builds from it with no host. Pure C, no ESP-IDF: tests/test_esp32_beacon.py compiles it.
   Layout and behaviour: docs/hardware_esp32.md, Portable beacon. */
#pragma once

#include <stddef.h>
#include <stdint.h>

#define ADVERT_MAGIC "PKSA"
#define ADVERT_LAYOUT 1
#define ADVERT_KIND_CYCLE 1
#define ADVERT_IMAGE_MAX 12288
#define ADVERT_FRAGMENTS_MAX 8
#define ADVERT_DISPLAY_MAX 4
#define ADVERT_PLAIN_MAX 0x500
#define ADVERT_HEADER_LEN 40          /* network id 32, version, format, u16 BE size, u32 BE nonce */
/* 802.11 header 24, LDN action head 12, header 40, SHA-256 or GCM tag 32, payload. */
#define ADVERT_FRAME_MAX (24 + 12 + ADVERT_HEADER_LEN + 32 + ADVERT_PLAIN_MAX)

enum { ADVERT_FORMAT_PLAIN = 1, ADVERT_FORMAT_AES_CTR = 2, ADVERT_FORMAT_AES_GCM = 3 };

typedef struct {
    uint8_t channel, bssid[6], ssid[32], data_key[16], max_stations;
    uint8_t advertise_key[16], header[ADVERT_HEADER_LEN];
    uint16_t interval_ms, dwell_ms;
    uint8_t count, display_count;
    const uint8_t *plain[ADVERT_FRAGMENTS_MAX];
    uint16_t plain_len[ADVERT_FRAGMENTS_MAX];
    const uint8_t *display[ADVERT_DISPLAY_MAX];
    uint16_t display_len[ADVERT_DISPLAY_MAX];
} advert_image_t;

/* Each returns 0 on success. */
typedef struct {
    int (*sha256)(const uint8_t *data, size_t length, uint8_t digest[32]);
    int (*aes_ctr)(const uint8_t key[16], const uint8_t counter[16], const uint8_t *in, uint8_t *out,
                   size_t length);
    int (*aes_gcm)(const uint8_t key[16], const uint8_t iv[12], const uint8_t *aad, size_t aad_length,
                   const uint8_t *in, uint8_t *out, size_t length, uint8_t tag[16]);
} advert_crypto_t;

uint32_t advert_crc32(const uint8_t *data, size_t length);
/* 0, or why the image is refused (1 size, 2 magic or layout, 3 kind, 4 crc, 5 fields); the
   image's pointers point into `data`, which must outlive it. */
int advert_parse(const uint8_t *data, size_t length, advert_image_t *image);
/* The action frame carrying fragment `index` under `nonce`; its length, or 0. */
size_t advert_frame(const advert_image_t *image, unsigned index, uint32_t nonce,
                    const advert_crypto_t *crypto, uint8_t out[ADVERT_FRAME_MAX]);
