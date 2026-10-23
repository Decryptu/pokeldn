/* The portable beacon's storage and crypto: the advert.h image kept in NVS, and PSA AES and SHA-256
   for advert_frame. docs/hardware_esp32.md, Portable beacon. */
#pragma once

#include <stddef.h>
#include <stdint.h>

#include "esp_err.h"

#include "advert.h"

extern const advert_crypto_t beacon_crypto;

/* Reads the stored image, if any, at boot. */
void beacon_load(void);
/* The stored image, parsed; NULL when none. */
const advert_image_t *beacon_image(void);
/* Stages `n` bytes at `offset` of the next image. */
esp_err_t beacon_write(uint32_t offset, const uint8_t *data, size_t n);
/* Checks the first `length` staged bytes and stores them in place of the image. */
esp_err_t beacon_commit(size_t length);
esp_err_t beacon_erase(void);
/* The stored image's length and CRC-32 (zlib's), both 0 when none. */
void beacon_identity(uint16_t *length, uint32_t *crc);
