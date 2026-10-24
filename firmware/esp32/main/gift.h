/* A FireRed/LeafGreen Mystery Gift the board hosts with no computer: the session bin/frlg_mg_host.py
   plays, above the access point the driver runs. Ethernet in, Ethernet out: LDN authentication
   (EtherType 0x88B7), ARP, IPv4/UDP, Pia, Reliable, the RFU leader and the Mystery Gift server.
   Pure C, no ESP-IDF: tests/test_esp32_gift.py compiles it against the Python host's peer.
   Each layer ports one Python module; a comment names it. docs/hardware_esp32.md, Portable beacon. */
#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "advert.h"

/* Records after an image's screen commands (pokeldn/ldn/portable.py, pokeldn/frlg/gift/portable.py):
   u8 tag, u16 length, bytes. */
enum {
    GIFT_RECORD_LDN = 1, GIFT_RECORD_PIA = 2,
    GIFT_RECORD_APP = 16, GIFT_RECORD_APP_ACTIVE = 17, GIFT_RECORD_LINK = 18, GIFT_RECORD_TIMING = 19,
    GIFT_RECORD_GAME = 20, GIFT_RECORD_PROGRAM = 21, GIFT_RECORD_PAYLOAD = 22, GIFT_RECORD_BUILD = 23,
};

#define GIFT_PAYLOADS_MAX 64
#define GIFT_BUILDS_MAX 16
#define GIFT_SLOTS_MAX 32
#define GIFT_APP_DATA_MAX 0x180
#define GIFT_ADVERT_MAX (40 + 48 * 2 + 2 + GIFT_APP_DATA_MAX)

typedef struct {
    uint8_t ident;
    uint16_t size;            /* 0: the console's whole 1024-byte buffer */
    const uint8_t *data;
    uint16_t length;
} gift_payload_t;

typedef struct {
    uint8_t code[4];          /* the cartridge's game code; four zeros serve any */
    uint16_t card_flag_id, card_icon, stamp_species, stamp_id;
    uint8_t card_max_stamps, slots;
    uint8_t slot[GIFT_SLOTS_MAX];
} gift_build_t;

typedef struct {
    const advert_image_t *advert;
    /* LDN: the advertisement plaintext up to and including the host's station entry, the
       authentication header's network id, the key the authentication key is decrypted from. */
    const uint8_t *advert_prefix;         /* 40 + 48 */
    const uint8_t *auth_network_id;       /* 32 */
    const uint8_t *auth_key_source;       /* 16 */
    const uint8_t *challenge_key;         /* 32 */
    uint64_t challenge, device_id;
    uint8_t version, platform;
    /* Pia */
    const uint8_t *session_key;           /* 16 */
    uint32_t pia_network_id;
    uint8_t host_ip[4];
    const uint8_t *host_player_id;        /* 16 */
    const uint8_t *host_name;
    uint8_t host_name_length;
    /* The FireRed host */
    const uint8_t *app_data, *app_data_active;
    uint16_t app_data_length, app_data_active_length;
    const uint8_t *link_player;           /* 200 */
    uint8_t rfu_session_id[2];
    uint16_t timing[8];                   /* MysteryGiftTiming, in field order */
    uint8_t flags;                        /* 1 native nonces, 2 join response first, 4 trust Pia */
    uint32_t tick_us;
    uint8_t game_family, expect_console;
    const uint8_t *program;
    uint16_t program_length;
    uint8_t payload_count, build_count;
    gift_payload_t payload[GIFT_PAYLOADS_MAX];
    gift_build_t build[GIFT_BUILDS_MAX];
} gift_image_t;

/* 0, or why the records are refused; the image's pointers point into `advert`'s data. */
int gift_parse(const advert_image_t *advert, gift_image_t *image);
size_t gift_image_size(void);

/* Each returns 0 on success. */
typedef struct {
    int (*sha256)(const uint8_t *data, size_t length, uint8_t digest[32]);
    int (*hmac_sha256)(const uint8_t *key, size_t key_length, const uint8_t *data, size_t length,
                       uint8_t mac[32]);
    int (*aes_decrypt_block)(const uint8_t key[16], const uint8_t in[16], uint8_t out[16]);
    int (*aes_encrypt_block)(const uint8_t key[16], const uint8_t in[16], uint8_t out[16]);
    int (*gcm_seal)(const uint8_t key[16], const uint8_t iv[12], const uint8_t *aad, size_t aad_length,
                    const uint8_t *in, uint8_t *out, size_t length, uint8_t *tag, size_t tag_length);
    /* 0 only when the tag is the data's */
    int (*gcm_open)(const uint8_t key[16], const uint8_t iv[12], const uint8_t *aad, size_t aad_length,
                    const uint8_t *in, uint8_t *out, size_t length, const uint8_t *tag,
                    size_t tag_length);
    uint32_t (*random)(void *context);
    /* An Ethernet frame for the access point to send, to a station or broadcast. */
    void (*send)(void *context, const uint8_t *frame, size_t length);
    /* A station to remove from the access point: the session refused or ended it. */
    void (*kick)(void *context, const uint8_t mac[6]);
    void (*event)(void *context, int event, int value);
    void *context;
} gift_platform_t;

enum {
    GIFT_EVENT_JOINED = 1,      /* the console authenticated */
    GIFT_EVENT_LINKED = 2,      /* its LinkPlayer block arrived */
    GIFT_EVENT_RESULT = 3,      /* the server finished; value is its SVR_MSG_* */
    GIFT_EVENT_LEFT = 4,        /* the session is over; value 1 when something was delivered */
    GIFT_EVENT_REFUSED = 5,     /* the console's game data refused it; value is why */
};

/* zstd's single-frame decoder (gift_zstd.c): the bytes written, or SIZE_MAX. */
size_t gift_zstd_decompress(const uint8_t *in, size_t length, uint8_t *out, size_t capacity);
bool gift_zstd_ready(void);

typedef struct gift_host gift_host_t;

size_t gift_host_size(void);
/* `memory` holds gift_host_size() bytes; the image and platform outlive the host. */
gift_host_t *gift_host_start(void *memory, const gift_image_t *image, const gift_platform_t *platform,
                             uint64_t now_us);
void gift_host_rx(gift_host_t *host, const uint8_t *frame, size_t length, uint64_t now_us);
/* A station's broadcast sent straight to the BSS (no DS bits, the group key, no FCS): the access
   point drops it, so the radio hands it over whole (docs/ldn.md, A station's broadcasts). */
void gift_host_rx_80211(gift_host_t *host, const uint8_t *frame, size_t length, uint64_t now_us);
/* A station associated (the driver's AP_STACONNECTED) or left. */
void gift_host_station(gift_host_t *host, const uint8_t mac[6], bool joined, uint64_t now_us);
/* Runs every timer due by `now_us`; returns when it next needs to run. */
uint64_t gift_host_poll(gift_host_t *host, uint64_t now_us);
/* The advertisement plaintext now, and a counter that changes with it (the nonce's offset). */
size_t gift_host_advert(const gift_host_t *host, uint8_t out[GIFT_ADVERT_MAX], uint32_t *version);
