#include "beacon.h"

#include <stdlib.h>
#include <string.h>

#include "nvs.h"
#include "psa/crypto.h"

#define NVS_SPACE "pokeldn"
#define NVS_KEY "beacon"

static uint8_t *s_stored, *s_staged;
static size_t s_stored_len;
static advert_image_t s_image;
static bool s_valid;
static gift_image_t s_gift;
static bool s_gift_valid;

static int sha256(const uint8_t *data, size_t length, uint8_t digest[32])
{
    size_t out = 0;
    return psa_hash_compute(PSA_ALG_SHA_256, data, length, digest, 32, &out) != PSA_SUCCESS || out != 32;
}

static psa_key_id_t import_key(const uint8_t key[16], psa_algorithm_t alg)
{
    psa_key_attributes_t attributes = PSA_KEY_ATTRIBUTES_INIT;
    psa_set_key_type(&attributes, PSA_KEY_TYPE_AES);
    psa_set_key_bits(&attributes, 128);
    psa_set_key_usage_flags(&attributes, PSA_KEY_USAGE_ENCRYPT);
    psa_set_key_algorithm(&attributes, alg);
    psa_key_id_t id = 0;
    return psa_import_key(&attributes, key, 16, &id) == PSA_SUCCESS ? id : 0;
}

/* advert_frame encrypts in place; PSA promises nothing for overlapping buffers. */
static uint8_t s_scratch[32 + ADVERT_PLAIN_MAX + 16];

static int aes_ctr(const uint8_t key[16], const uint8_t counter[16], const uint8_t *in, uint8_t *out,
                   size_t length)
{
    if (length > sizeof(s_scratch)) return 1;
    const psa_key_id_t id = import_key(key, PSA_ALG_CTR);
    if (!id) return 1;
    psa_cipher_operation_t op = PSA_CIPHER_OPERATION_INIT;
    size_t done = 0, tail = 0;
    psa_status_t s = psa_cipher_encrypt_setup(&op, id, PSA_ALG_CTR);
    if (s == PSA_SUCCESS) s = psa_cipher_set_iv(&op, counter, 16);
    if (s == PSA_SUCCESS) s = psa_cipher_update(&op, in, length, s_scratch, sizeof(s_scratch), &done);
    if (s == PSA_SUCCESS) s = psa_cipher_finish(&op, s_scratch + done, sizeof(s_scratch) - done, &tail);
    psa_cipher_abort(&op);
    psa_destroy_key(id);
    if (s != PSA_SUCCESS || done + tail != length) return 1;
    memcpy(out, s_scratch, length);
    return 0;
}

static int aes_gcm(const uint8_t key[16], const uint8_t iv[12], const uint8_t *aad, size_t aad_length,
                   const uint8_t *in, uint8_t *out, size_t length, uint8_t tag[16])
{
    if (length + 16 > sizeof(s_scratch)) return 1;
    const psa_key_id_t id = import_key(key, PSA_ALG_GCM);
    if (!id) return 1;
    size_t done = 0;
    const psa_status_t s = psa_aead_encrypt(id, PSA_ALG_GCM, iv, 12, aad, aad_length, in, length,
                                            s_scratch, sizeof(s_scratch), &done);
    psa_destroy_key(id);
    if (s != PSA_SUCCESS || done != length + 16) return 1;
    memcpy(out, s_scratch, length);           /* PSA writes ciphertext then tag; LDN wants tag first */
    memcpy(tag, s_scratch + length, 16);
    return 0;
}

const advert_crypto_t beacon_crypto = {sha256, aes_ctr, aes_gcm};

static int hmac_sha256(const uint8_t *key, size_t key_length, const uint8_t *data, size_t length,
                       uint8_t mac[32])
{
    psa_key_attributes_t attributes = PSA_KEY_ATTRIBUTES_INIT;
    psa_set_key_type(&attributes, PSA_KEY_TYPE_HMAC);
    psa_set_key_bits(&attributes, PSA_BYTES_TO_BITS(key_length));
    psa_set_key_usage_flags(&attributes, PSA_KEY_USAGE_SIGN_MESSAGE);
    psa_set_key_algorithm(&attributes, PSA_ALG_HMAC(PSA_ALG_SHA_256));
    psa_key_id_t id = 0;
    if (psa_import_key(&attributes, key, key_length, &id) != PSA_SUCCESS) return 1;
    size_t out = 0;
    const psa_status_t s = psa_mac_compute(id, PSA_ALG_HMAC(PSA_ALG_SHA_256), data, length, mac, 32, &out);
    psa_destroy_key(id);
    return s != PSA_SUCCESS || out != 32;
}

static int aes_block(const uint8_t key[16], const uint8_t in[16], uint8_t out[16], bool encrypt)
{
    psa_key_attributes_t attributes = PSA_KEY_ATTRIBUTES_INIT;
    psa_set_key_type(&attributes, PSA_KEY_TYPE_AES);
    psa_set_key_bits(&attributes, 128);
    psa_set_key_usage_flags(&attributes, encrypt ? PSA_KEY_USAGE_ENCRYPT : PSA_KEY_USAGE_DECRYPT);
    psa_set_key_algorithm(&attributes, PSA_ALG_ECB_NO_PADDING);
    psa_key_id_t id = 0;
    if (psa_import_key(&attributes, key, 16, &id) != PSA_SUCCESS) return 1;
    size_t done = 0;
    const psa_status_t s = encrypt ? psa_cipher_encrypt(id, PSA_ALG_ECB_NO_PADDING, in, 16, out, 16, &done)
                                   : psa_cipher_decrypt(id, PSA_ALG_ECB_NO_PADDING, in, 16, out, 16, &done);
    psa_destroy_key(id);
    return s != PSA_SUCCESS || done != 16;
}

static int aes_decrypt_block(const uint8_t key[16], const uint8_t in[16], uint8_t out[16])
{
    return aes_block(key, in, out, false);
}

static int aes_encrypt_block(const uint8_t key[16], const uint8_t in[16], uint8_t out[16])
{
    return aes_block(key, in, out, true);
}

static psa_key_id_t gcm_key(const uint8_t key[16], psa_algorithm_t alg)
{
    psa_key_attributes_t attributes = PSA_KEY_ATTRIBUTES_INIT;
    psa_set_key_type(&attributes, PSA_KEY_TYPE_AES);
    psa_set_key_bits(&attributes, 128);
    psa_set_key_usage_flags(&attributes, PSA_KEY_USAGE_ENCRYPT | PSA_KEY_USAGE_DECRYPT);
    psa_set_key_algorithm(&attributes, alg);
    psa_key_id_t id = 0;
    return psa_import_key(&attributes, key, 16, &id) == PSA_SUCCESS ? id : 0;
}

/* PSA puts the tag after the ciphertext; gift.h keeps them apart. One task uses these at a time. */
static uint8_t s_gcm[1600 + 16];

static int gcm_seal(const uint8_t key[16], const uint8_t iv[12], const uint8_t *aad, size_t aad_length,
                    const uint8_t *in, uint8_t *out, size_t length, uint8_t *tag, size_t tag_length)
{
    if (length + 16 > sizeof(s_gcm) || tag_length < 4 || tag_length > 16) return 1;
    const psa_algorithm_t alg = PSA_ALG_AEAD_WITH_SHORTENED_TAG(PSA_ALG_GCM, tag_length);
    const psa_key_id_t id = gcm_key(key, alg);
    if (!id) return 1;
    size_t done = 0;
    const psa_status_t s = psa_aead_encrypt(id, alg, iv, 12, aad, aad_length, in, length, s_gcm,
                                            sizeof(s_gcm), &done);
    psa_destroy_key(id);
    if (s != PSA_SUCCESS || done != length + tag_length) return 1;
    memcpy(out, s_gcm, length);
    memcpy(tag, s_gcm + length, tag_length);
    return 0;
}

static int gcm_open(const uint8_t key[16], const uint8_t iv[12], const uint8_t *aad, size_t aad_length,
                    const uint8_t *in, uint8_t *out, size_t length, const uint8_t *tag, size_t tag_length)
{
    if (length + 16 > sizeof(s_gcm) || tag_length < 4 || tag_length > 16) return 1;
    const psa_algorithm_t alg = PSA_ALG_AEAD_WITH_SHORTENED_TAG(PSA_ALG_GCM, tag_length);
    const psa_key_id_t id = gcm_key(key, alg);
    if (!id) return 1;
    memcpy(s_gcm, in, length);
    memcpy(s_gcm + length, tag, tag_length);
    size_t done = 0;
    const psa_status_t s = psa_aead_decrypt(id, alg, iv, 12, aad, aad_length, s_gcm, length + tag_length,
                                            out, length, &done);
    psa_destroy_key(id);
    return s != PSA_SUCCESS || done != length;
}

void beacon_gift_crypto(gift_platform_t *platform)
{
    platform->sha256 = sha256;
    platform->hmac_sha256 = hmac_sha256;
    platform->aes_decrypt_block = aes_decrypt_block;
    platform->aes_encrypt_block = aes_encrypt_block;
    platform->gcm_seal = gcm_seal;
    platform->gcm_open = gcm_open;
}

const gift_image_t *beacon_gift(void)
{
    return s_valid && s_gift_valid ? &s_gift : NULL;
}

static void keep(uint8_t *data, size_t length)
{
    free(s_stored);
    s_stored = data;
    s_stored_len = data ? length : 0;
    s_valid = data && advert_parse(data, length, &s_image) == 0;
    s_gift_valid = s_valid && s_image.kind == ADVERT_KIND_HOST && gift_parse(&s_image, &s_gift) == 0;
    if (s_valid && s_image.kind == ADVERT_KIND_HOST && !s_gift_valid) s_valid = false;
}

void beacon_load(void)
{
    nvs_handle_t nvs;
    if (nvs_open(NVS_SPACE, NVS_READONLY, &nvs) != ESP_OK) return;
    size_t length = 0;
    if (nvs_get_blob(nvs, NVS_KEY, NULL, &length) == ESP_OK && length && length <= ADVERT_IMAGE_MAX) {
        uint8_t *data = malloc(length);
        if (data && nvs_get_blob(nvs, NVS_KEY, data, &length) == ESP_OK) keep(data, length);
        else free(data);
    }
    nvs_close(nvs);
}

const advert_image_t *beacon_image(void)
{
    return s_valid ? &s_image : NULL;
}

esp_err_t beacon_write(uint32_t offset, const uint8_t *data, size_t n)
{
    if (offset > ADVERT_IMAGE_MAX || n > ADVERT_IMAGE_MAX - offset) return ESP_ERR_INVALID_SIZE;
    if (!s_staged && !(s_staged = calloc(1, ADVERT_IMAGE_MAX))) return ESP_ERR_NO_MEM;
    memcpy(s_staged + offset, data, n);
    return ESP_OK;
}

esp_err_t beacon_commit(size_t length)
{
    static const esp_err_t REFUSED[] = {ESP_OK, ESP_ERR_INVALID_SIZE, ESP_ERR_INVALID_VERSION,
                                        ESP_ERR_NOT_SUPPORTED, ESP_ERR_INVALID_CRC, ESP_ERR_INVALID_ARG};
    if (!s_staged || length > ADVERT_IMAGE_MAX) return ESP_ERR_INVALID_STATE;
    advert_image_t check;
    const int refused = advert_parse(s_staged, length, &check);
    if (refused) return REFUSED[refused];
    if (check.kind == ADVERT_KIND_HOST) {
        static gift_image_t gift;
        if (gift_parse(&check, &gift)) return ESP_ERR_INVALID_ARG;
    }
    nvs_handle_t nvs;
    esp_err_t r = nvs_open(NVS_SPACE, NVS_READWRITE, &nvs);
    if (r != ESP_OK) return r;
    r = nvs_set_blob(nvs, NVS_KEY, s_staged, length);
    if (r == ESP_OK) r = nvs_commit(nvs);
    nvs_close(nvs);
    if (r != ESP_OK) return r;
    uint8_t *data = realloc(s_staged, length);
    keep(data ? data : s_staged, length);
    s_staged = NULL;
    return ESP_OK;
}

esp_err_t beacon_erase(void)
{
    nvs_handle_t nvs;
    esp_err_t r = nvs_open(NVS_SPACE, NVS_READWRITE, &nvs);
    if (r != ESP_OK) return r;
    r = nvs_erase_key(nvs, NVS_KEY);
    if (r == ESP_OK || r == ESP_ERR_NVS_NOT_FOUND) r = nvs_commit(nvs);
    nvs_close(nvs);
    if (r == ESP_OK) keep(NULL, 0);
    return r;
}

void beacon_identity(uint16_t *length, uint32_t *crc)
{
    *length = s_valid ? (uint16_t)s_stored_len : 0;
    *crc = s_valid ? advert_crc32(s_stored, s_stored_len) : 0;
}
