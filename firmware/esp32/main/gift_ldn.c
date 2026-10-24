/* The gift host's LDN side: the image's records, the advertisement as stations sit down, the
   authentication frames (vendor/LDN APNetwork, AuthenticationFrame, ChallengeRequest/Response),
   ARP and IPv4/UDP (pokeldn/ldn/userspace_ip.py), and the run loop of
   pokeldn/frlg/link/host_app.py: one console at a time, then the next. */
#include <string.h>

#include "gift_int.h"

#define ETH_P_IP 0x0800
#define ETH_P_ARP 0x0806
#define ETH_P_LDN 0x88B7
#define PIA_PORT 12345
#define AUTH_HEADER 72
#define AUTH_SUCCESS 0
#define AUTH_DENIED_BY_POLICY 1
#define AUTH_MALFORMED_REQUEST 2
#define AUTH_INVALID_VERSION 4
#define AUTH_CHALLENGE_FAILURE 6
#define CLOSE_SETTLE_US 2000000          /* HOST_CLOSE_SETTLE_SECONDS */
/* No traffic from a seated console for this long, or a finished one that never leaves: the seat is
   given back. The computer's host has --idle-timeout; the board cannot be asked. */
#define IDLE_TIMEOUT_US 60000000
#define DONE_TIMEOUT_US 30000000

static const uint8_t BROADCAST_MAC[6] = {0xff, 0xff, 0xff, 0xff, 0xff, 0xff};
static const uint8_t AUTH_MAGIC[6] = {0x00, 0x22, 0xaa, 0x01, 0x02, 0x00};

/* ---- records ---- */

int gift_parse(const advert_image_t *advert, gift_image_t *im)
{
    memset(im, 0, sizeof(*im));
    im->advert = advert;
    if (advert->kind != ADVERT_KIND_HOST) return 1;
    unsigned seen = 0;
    uint8_t slots = 0;
    const uint8_t *p = advert->records, *end = advert->records + advert->records_len;
    while (p < end) {
        if (end - p < 3) return 2;
        const uint8_t tag = p[0];
        const uint16_t n = gl16(p + 1);
        const uint8_t *d = p + 3;
        if (end - d < n) return 2;
        p = d + n;
        switch (tag) {
        case GIFT_RECORD_LDN:
            if (n != 88 + 32 + 16 + 32 + 18) return 3;
            im->advert_prefix = d;
            im->auth_network_id = d + 88;
            im->auth_key_source = d + 120;
            im->challenge_key = d + 136;
            for (int i = 7; i >= 0; --i) im->challenge = im->challenge << 8 | d[168 + i];
            for (int i = 7; i >= 0; --i) im->device_id = im->device_id << 8 | d[176 + i];
            im->version = d[184];
            im->platform = d[185];
            break;
        case GIFT_RECORD_PIA:
            if (n < 40 || n > 80) return 3;
            im->session_key = d;
            im->pia_network_id = gl32(d + 16);
            memcpy(im->host_ip, d + 20, 4);
            im->host_player_id = d + 24;
            im->host_name = d + 40;
            im->host_name_length = (uint8_t)(n - 40);
            break;
        case GIFT_RECORD_APP:
        case GIFT_RECORD_APP_ACTIVE:
            if (n > GIFT_APP_DATA_MAX) return 3;
            if (tag == GIFT_RECORD_APP) { im->app_data = d; im->app_data_length = n; }
            else { im->app_data_active = d; im->app_data_active_length = n; }
            break;
        case GIFT_RECORD_LINK:
            if (n != 202) return 3;
            im->link_player = d;
            memcpy(im->rfu_session_id, d + 200, 2);
            break;
        case GIFT_RECORD_TIMING:
            if (n != 21) return 3;
            for (int i = 0; i < 8; ++i) im->timing[i] = gl16(d + 2 * i);
            im->flags = d[16];
            im->tick_us = gl32(d + 17);
            if (im->tick_us < 1000) return 3;
            break;
        case GIFT_RECORD_GAME:
            if (n != 2 || d[0] > 1 || d[1] > 3) return 3;
            im->game_family = d[0];
            im->expect_console = d[1];
            break;
        case GIFT_RECORD_PROGRAM:
            if (!n) return 3;
            im->program = d;
            im->program_length = n;
            break;
        case GIFT_RECORD_PAYLOAD: {
            if (n < 3 || im->payload_count == GIFT_PAYLOADS_MAX) return 3;
            gift_payload_t *pl = &im->payload[im->payload_count++];
            pl->ident = d[0];
            pl->size = gl16(d + 1);
            pl->data = d + 3;
            pl->length = (uint16_t)(n - 3);
            if (pl->size > 1024 || pl->length > (pl->size ? pl->size : 1024)) return 3;
            break;
        }
        case GIFT_RECORD_BUILD: {
            if (n < 14 || im->build_count == GIFT_BUILDS_MAX) return 3;
            gift_build_t *b = &im->build[im->build_count++];
            memcpy(b->code, d, 4);
            b->card_flag_id = gl16(d + 4);
            b->card_icon = gl16(d + 6);
            b->card_max_stamps = d[8];
            b->stamp_species = gl16(d + 9);
            b->stamp_id = gl16(d + 11);
            b->slots = d[13];
            if (n != 14 + b->slots || b->slots > GIFT_SLOTS_MAX) return 3;
            if (im->build_count > 1 && b->slots != slots) return 3;
            slots = b->slots;
            memcpy(b->slot, d + 14, b->slots);
            break;
        }
        default:
            return 4;
        }
        if (tag < 32) seen |= 1u << tag;
    }
    const unsigned need = 1u << GIFT_RECORD_LDN | 1u << GIFT_RECORD_PIA | 1u << GIFT_RECORD_APP |
                          1u << GIFT_RECORD_APP_ACTIVE | 1u << GIFT_RECORD_LINK | 1u << GIFT_RECORD_TIMING |
                          1u << GIFT_RECORD_GAME | 1u << GIFT_RECORD_PROGRAM | 1u << GIFT_RECORD_BUILD;
    if ((seen & need) != need) return 5;
    for (uint8_t i = 0; i < im->build_count; ++i)
        for (uint8_t k = 0; k < im->build[i].slots; ++k)
            if (im->build[i].slot[k] >= im->payload_count) return 6;
    return 0;
}

/* ---- the advertisement ---- */

size_t gift_host_advert(const gift_host_t *h, uint8_t out[GIFT_ADVERT_MAX], uint32_t *version)
{
    const gift_image_t *im = h->image;
    memcpy(out, im->advert_prefix, 88);
    size_t n = 88;
    out[39] = (uint8_t)(1 + (h->station.seated ? 1 : 0));
    if (h->station.seated) {
        uint8_t *s = out + n;
        memset(s, 0, 48);
        memcpy(s, h->station.ip, 4);
        memcpy(s + 4, h->station.mac, 6);
        s[10] = 1;
        s[11] = h->station.platform;
        memcpy(s + 12, h->station.name, 32);
        n += 48;
    }
    const uint8_t *app = h->app_active ? im->app_data_active : im->app_data;
    const uint16_t length = h->app_active ? im->app_data_active_length : im->app_data_length;
    pb16(out + n, length);
    memcpy(out + n + 2, app, length);
    *version = h->advert_version;
    return n + 2 + length;
}

void gift_note_app_active(gift_host_t *h)
{
    h->app_active = true;
    ++h->advert_version;
}

/* ---- Ethernet, ARP, IPv4, UDP ---- */

static void ethernet(gift_host_t *h, const uint8_t dst[6], uint16_t type, uint8_t *frame)
{
    memcpy(frame, dst, 6);
    memcpy(frame + 6, h->image->advert->bssid, 6);
    pb16(frame + 12, type);
}

static uint16_t checksum(const uint8_t *data, size_t length, uint32_t sum)
{
    for (size_t i = 0; i + 1 < length; i += 2) sum += gb16(data + i);
    if (length & 1) sum += (uint32_t)data[length - 1] << 8;
    while (sum >> 16) sum = (sum & 0xFFFF) + (sum >> 16);
    return (uint16_t)~sum;
}

void gift_send_udp(gift_host_t *h, const uint8_t dst_ip[4], const uint8_t *payload, size_t length)
{
    const uint8_t *mac;
    if (dst_ip[3] == 255 || !memcmp(dst_ip, "\xff\xff\xff\xff", 4)) mac = BROADCAST_MAC;
    else if (h->station.seated && !memcmp(dst_ip, h->station.ip, 4)) mac = h->station.mac;
    else return;
    if (length + 14 + 28 > sizeof(h->frame)) return;
    static uint8_t frame[1600];
    ethernet(h, mac, ETH_P_IP, frame);
    uint8_t *ip = frame + 14, *udp = ip + 20;
    const uint16_t udp_length = (uint16_t)(8 + length);
    memmove(udp + 8, payload, length);
    pb16(udp, PIA_PORT);
    pb16(udp + 2, PIA_PORT);
    pb16(udp + 4, udp_length);
    pb16(udp + 6, 0);
    uint32_t pseudo = gb16(h->image->host_ip) + gb16(h->image->host_ip + 2) + gb16(dst_ip) + gb16(dst_ip + 2) +
                      17 + udp_length;
    uint16_t sum = checksum(udp, udp_length, pseudo);
    pb16(udp + 6, sum ? sum : 0xFFFF);
    ip[0] = 0x45;
    ip[1] = 0;
    pb16(ip + 2, (uint16_t)(20 + udp_length));
    pb16(ip + 4, ++h->ip_ident);
    pb16(ip + 6, 0);
    ip[8] = 64;
    ip[9] = 17;
    pb16(ip + 10, 0);
    memcpy(ip + 12, h->image->host_ip, 4);
    memcpy(ip + 16, dst_ip, 4);
    pb16(ip + 10, checksum(ip, 20, 0));
    h->platform->send(h->platform->context, frame, 14 + 20 + udp_length);
}

static void on_arp(gift_host_t *h, const uint8_t *arp, size_t n)
{
    if (n < 28 || gb16(arp + 6) != 1 || memcmp(arp + 24, h->image->host_ip, 4)) return;
    uint8_t frame[14 + 28];
    ethernet(h, arp + 8, ETH_P_ARP, frame);
    uint8_t *a = frame + 14;
    pb16(a, 1);
    pb16(a + 2, ETH_P_IP);
    a[4] = 6;
    a[5] = 4;
    pb16(a + 6, 2);
    memcpy(a + 8, h->image->advert->bssid, 6);
    memcpy(a + 14, h->image->host_ip, 4);
    memcpy(a + 18, arp + 8, 6);
    memcpy(a + 24, arp + 14, 4);
    h->platform->send(h->platform->context, frame, sizeof(frame));
}

static void on_ip(gift_host_t *h, const uint8_t *ip, size_t n)
{
    if (n < 20 || ip[0] >> 4 != 4) return;
    const size_t ihl = (size_t)(ip[0] & 0x0F) * 4, total = gb16(ip + 2);
    if (total > n || total < ihl + 8 || (gb16(ip + 6) & 0x3FFF)) return;   /* no fragments */
    const uint8_t *dst = ip + 16, *src = ip + 12;
    const bool ours = !memcmp(dst, h->image->host_ip, 4) || dst[3] == 255;
    if (!ours || ip[9] != 17 || !memcmp(src, h->image->host_ip, 4)) return;
    const uint8_t *udp = ip + ihl;
    if (gb16(udp + 2) != PIA_PORT) return;
    const size_t udp_length = gb16(udp + 4);
    if (udp_length < 8 || ihl + udp_length > total) return;
    pia_receive(h, udp + 8, udp_length - 8, src);
}

/* ---- authentication ---- */

static bool auth_key(gift_host_t *h, const uint8_t client_random[16], uint8_t key[16])
{
    uint8_t digest[32];
    return !h->platform->sha256(client_random, 16, digest) &&
           !h->platform->aes_decrypt_block(h->image->auth_key_source, digest, key);
}

static void auth_respond(gift_host_t *h, const uint8_t mac[6], uint8_t status, const uint8_t client_random[16],
                         const uint8_t *challenge)
{
    const gift_image_t *im = h->image;
    uint8_t payload[132 + 256] = {0};
    payload[0] = im->platform;
    size_t n = im->version >= 3 ? 132 : 0;
    if (challenge && im->version >= 3) {
        memcpy(payload + 132, challenge, 256);
        n += 256;
    }
    uint8_t *frame = h->frame;
    ethernet(h, mac, ETH_P_LDN, frame);
    uint8_t *f = frame + 14, *header = f + 6;
    memcpy(f, AUTH_MAGIC, 6);
    memset(header, 0, AUTH_HEADER);
    header[0] = im->version;
    header[1] = (uint8_t)n;
    header[2] = status;
    header[3] = 1;
    header[4] = (uint8_t)(n >> 8);
    header[5] = 1;                       /* AUTH_FORMAT_AES_GCM */
    memcpy(header + 8, im->auth_network_id, 32);
    memcpy(header + 40, im->advert_prefix, 16);   /* the server random */
    memcpy(header + 56, client_random, 16);
    uint8_t key[16];
    if (!auth_key(h, client_random, key) ||
        h->platform->gcm_seal(key, header, header, AUTH_HEADER, payload, f + 6 + AUTH_HEADER + 16, n,
                              f + 6 + AUTH_HEADER, 16))
        return;
    h->platform->send(h->platform->context, frame, 14 + 6 + AUTH_HEADER + 16 + n);
}

static void reset_session(gift_host_t *h);

static void seat(gift_host_t *h, const uint8_t mac[6], const uint8_t *request)
{
    station_t *s = &h->station;
    s->seated = s->associated = true;
    memcpy(s->mac, mac, 6);
    memcpy(s->ip, h->image->host_ip, 3);
    s->ip[3] = 2;                        /* participant index 1 */
    memcpy(s->name, request, 32);
    s->platform = request[34];
    ++h->advert_version;
    h->active = true;
    h->absence_logged = false;
    h->seated_us = h->now_us;
    pia_participant_joined(h);
    if (h->platform->event) h->platform->event(h->platform->context, GIFT_EVENT_JOINED, 0);
}

static void on_auth(gift_host_t *h, const uint8_t mac[6], const uint8_t *f, size_t n)
{
    static const uint8_t zero[16] = {0};
    const gift_image_t *im = h->image;
    if (n < 6 + AUTH_HEADER + 16 || memcmp(f, AUTH_MAGIC, 6)) {
        auth_respond(h, mac, AUTH_MALFORMED_REQUEST, zero, NULL);
        return;
    }
    const uint8_t *header = f + 6, *client_random = header + 56;
    const size_t size = header[1] | header[4] << 8;
    if (header[5] != 1 || n - (6 + AUTH_HEADER + 16) != size || size > sizeof(h->scratch)) {
        auth_respond(h, mac, AUTH_MALFORMED_REQUEST, zero, NULL);
        return;
    }
    uint8_t key[16], *request = h->scratch;
    if (!auth_key(h, client_random, key) ||
        h->platform->gcm_open(key, header, header, AUTH_HEADER, f + 6 + AUTH_HEADER + 16, request, size,
                              f + 6 + AUTH_HEADER, 16) ||
        size < 64) {
        auth_respond(h, mac, AUTH_MALFORMED_REQUEST, zero, NULL);
        return;
    }
    const uint8_t version = header[0];
    if (version < 2 || version > 4) { auth_respond(h, mac, AUTH_INVALID_VERSION, client_random, NULL); return; }
    if (header[2] != 0 || header[3] != 0 || memcmp(header + 8, im->auth_network_id, 32) ||
        memcmp(header + 40, im->advert_prefix, 16)) {
        auth_respond(h, mac, AUTH_MALFORMED_REQUEST, client_random, NULL);
        return;
    }
    if (h->station.seated && memcmp(h->station.mac, mac, 6)) {
        auth_respond(h, mac, AUTH_DENIED_BY_POLICY, client_random, NULL);
        return;
    }
    /* ChallengeRequest: u32, HMAC-SHA256, 12 bytes, then the 0x2D0-byte body it covers */
    const uint8_t *challenge = request + 64 + 0x24;
    uint8_t mac32[32];
    if (version < 3 || size != 64 + 0x24 + 0x300 ||
        h->platform->hmac_sha256(im->challenge_key, 32, challenge + 48, 0x2D0, mac32) ||
        memcmp(mac32, challenge + 4, 32)) {
        auth_respond(h, mac, AUTH_CHALLENGE_FAILURE, client_random, NULL);
        return;
    }
    const uint8_t *body = challenge + 48;
    uint64_t token = 0;
    for (int i = 7; i >= 0; --i) token = token << 8 | body[8 + i];
    if (token != im->challenge) {
        auth_respond(h, mac, AUTH_CHALLENGE_FAILURE, client_random, NULL);
        return;
    }
    /* ChallengeResponse: flags 2, the request's nonce and device, the host's device, its extra bytes */
    uint8_t answer[256] = {0}, *rb = answer + 48;
    pl32(rb + 4, 2);
    memcpy(rb + 8, body + 16, 8);
    memcpy(rb + 16, body + 24, 8);
    for (int i = 0; i < 8; ++i) rb[24 + i] = (uint8_t)(im->device_id >> (8 * i));
    memcpy(rb + 32, body + 32, 16);
    if (h->platform->hmac_sha256(im->challenge_key, 32, rb, 0xD0, answer + 4)) return;
    if (!h->station.seated) seat(h, mac, request);
    auth_respond(h, mac, AUTH_SUCCESS, client_random, answer);
}

/* ---- the session ---- */

static void reset_session(gift_host_t *h)
{
    memset(&h->station, 0, sizeof(h->station));
    h->active = h->ending = h->app_active = false;
    ++h->advert_version;
    pia_reset(h);
    session_reset(h);
    mg_reset(h);
}

static void end_session(gift_host_t *h, bool kick)
{
    if (kick && h->station.seated && h->platform->kick) h->platform->kick(h->platform->context, h->station.mac);
    if (h->platform->event) h->platform->event(h->platform->context, GIFT_EVENT_LEFT, h->mg.gift_sent);
    reset_session(h);
}

size_t gift_host_size(void) { return sizeof(gift_host_t); }

size_t gift_image_size(void) { return sizeof(gift_image_t); }

gift_host_t *gift_host_start(void *memory, const gift_image_t *image, const gift_platform_t *platform,
                             uint64_t now_us)
{
    gift_host_t *h = memory;
    memset(h, 0, sizeof(*h));
    h->image = image;
    h->platform = platform;
    h->now_us = now_us;
    reset_session(h);
    return h;
}

void gift_host_rx(gift_host_t *h, const uint8_t *frame, size_t length, uint64_t now_us)
{
    h->now_us = now_us;
    if (length < 14) return;
    const uint8_t *dst = frame, *src = frame + 6;
    if (memcmp(dst, h->image->advert->bssid, 6) && !(dst[0] & 1)) return;
    const uint16_t type = gb16(frame + 12);
    if (type == ETH_P_LDN) on_auth(h, src, frame + 14, length - 14);
    else if (type == ETH_P_ARP) on_arp(h, frame + 14, length - 14);
    else if (type == ETH_P_IP && h->active) on_ip(h, frame + 14, length - 14);
}

/* AES-CCM with an 8-byte MIC and a 13-byte nonce (RFC 3610, M=8, L=2): 0 when authentic. */
static int ccm_open(gift_host_t *h, const uint8_t key[16], const uint8_t nonce[13], const uint8_t *aad,
                    size_t aad_length, const uint8_t *in, size_t length, const uint8_t mic[8], uint8_t *out)
{
    int (*block)(const uint8_t[16], const uint8_t[16], uint8_t[16]) = h->platform->aes_encrypt_block;
    uint8_t a[16], s[16], x[16] = {0}, b[16];
    a[0] = 0x01;
    memcpy(a + 1, nonce, 13);
    for (size_t at = 0, counter = 1; at < length; at += 16, ++counter) {
        pb16(a + 14, (uint16_t)counter);
        if (block(key, a, s)) return 1;
        for (size_t i = 0; i < 16 && at + i < length; ++i) out[at + i] = in[at + i] ^ s[i];
    }
    b[0] = 0x59;                          /* Adata, M=8, L=2 */
    memcpy(b + 1, nonce, 13);
    pb16(b + 14, (uint16_t)length);
    for (int i = 0; i < 16; ++i) x[i] ^= b[i];
    if (block(key, x, x)) return 1;
    uint8_t pad[16];
    for (size_t at = 0, i = 0; at < aad_length + 2; at += 16) {
        memset(pad, 0, 16);
        for (size_t k = 0; k < 16 && at + k < aad_length + 2; ++k, ++i)
            pad[k] = i == 0 ? (uint8_t)(aad_length >> 8) : i == 1 ? (uint8_t)aad_length : aad[i - 2];
        for (int k = 0; k < 16; ++k) x[k] ^= pad[k];
        if (block(key, x, x)) return 1;
    }
    for (size_t at = 0; at < length; at += 16) {
        for (size_t k = 0; k < 16 && at + k < length; ++k) x[k] ^= out[at + k];
        if (block(key, x, x)) return 1;
    }
    pb16(a + 14, 0);
    if (block(key, a, s)) return 1;
    uint8_t diff = 0;
    for (int i = 0; i < 8; ++i) diff |= (uint8_t)(x[i] ^ s[i] ^ mic[i]);
    return diff != 0;
}

void gift_host_rx_80211(gift_host_t *h, const uint8_t *f, size_t n, uint64_t now_us)
{
    h->now_us = now_us;
    const uint8_t *bssid = h->image->advert->bssid;
    if (n < 24 + 8 + 8 + 8 || n > sizeof(h->scratch)) return;
    const uint16_t fc = gl16(f);
    const uint8_t subtype = (fc >> 4) & 0xF;
    if (((fc >> 2) & 3) != 2 || (subtype != 0 && subtype != 8) || (fc & 0x0300) || !(fc & 0x4000)) return;
    if (memcmp(f + 16, bssid, 6) || !memcmp(f + 10, bssid, 6)) return;
    size_t at = 24;
    uint8_t tid = 0;
    if (subtype == 8) {
        if (f[24] & 0x80) return;         /* A-MSDU */
        tid = f[24] & 0xF;
        at += 2;
    }
    const uint8_t *ccmp = f + at;
    if (!(ccmp[3] & 0x20) || n < at + 8 + 8 + 8) return;   /* the extended IV */
    /* the nonce: priority, the transmitter, the packet number big-endian [vendor/LDN wlan.DataFrame] */
    uint8_t nonce[13] = {tid};
    memcpy(nonce + 1, f + 10, 6);
    const uint8_t pn[6] = {ccmp[7], ccmp[6], ccmp[5], ccmp[4], ccmp[1], ccmp[0]};
    memcpy(nonce + 7, pn, 6);
    uint8_t aad[24 + 2] = {0};
    pl16(aad, (uint16_t)(0x0008 | (subtype == 8 ? 0x80 : 0) | 0x4000));
    memcpy(aad + 2, f + 4, 18);
    size_t aad_length = 22;
    if (subtype == 8) {
        pl16(aad + 22, tid);
        aad_length = 24;
    }
    const size_t length = n - at - 8 - 8;
    uint8_t *plain = h->scratch;
    if (ccm_open(h, h->image->advert->data_key, nonce, aad, aad_length, ccmp + 8, length, f + n - 8, plain)) return;
    static const uint8_t snap[6] = {0xAA, 0xAA, 0x03, 0, 0, 0};
    if (length < 8 || memcmp(plain, snap, 6)) return;
    static uint8_t frame[1600];
    memcpy(frame, f + 4, 6);
    memcpy(frame + 6, f + 10, 6);
    memcpy(frame + 12, plain + 6, length - 6);
    gift_host_rx(h, frame, 12 + length - 6, now_us);
}

void gift_host_station(gift_host_t *h, const uint8_t mac[6], bool joined, uint64_t now_us)
{
    h->now_us = now_us;
    if (joined) {
        if (!h->station.seated) {
            h->station.associated = true;
            memcpy(h->station.mac, mac, 6);
        }
        return;
    }
    if (!h->station.seated || memcmp(h->station.mac, mac, 6)) return;
    /* _absence_stop_reason: a console that confirmed the close gets the settle; any other ends now */
    h->station.seated = false;
    ++h->advert_version;
    h->session.stopped = true;
    if (!h->mg.close_confirmed || h->mg.done) {
        end_session(h, false);
        return;
    }
    h->ending = true;
    h->absent_since_us = now_us;
}

uint64_t gift_host_poll(gift_host_t *h, uint64_t now_us)
{
    h->now_us = now_us;
    if (h->ending) {
        if (now_us - h->absent_since_us >= CLOSE_SETTLE_US) end_session(h, false);
        return now_us + 50000;
    }
    if (!h->active) return now_us + 50000;
    if (h->mg.failed) {
        end_session(h, true);
        return now_us + 50000;
    }
    const uint64_t last = h->pia.have_rx && h->pia.last_rx_us > h->seated_us ? h->pia.last_rx_us : h->seated_us;
    if (now_us - last >= IDLE_TIMEOUT_US) {
        end_session(h, true);
        return now_us + 50000;
    }
    if (h->mg.done && !h->absence_logged) {
        h->absence_logged = true;
        h->absent_since_us = now_us;
    }
    if (h->mg.done && now_us - h->absent_since_us >= DONE_TIMEOUT_US) {
        end_session(h, true);
        return now_us + 50000;
    }
    return pia_tick(h);
}
