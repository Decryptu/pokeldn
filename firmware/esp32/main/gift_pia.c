/* Pia 6.39 as the GBA application's host speaks it: pokeldn/ldn/crypto.py (PiaCrypto, the header),
   reliable.py (message tiling), pia_connect.py (Net, Session, RTT codecs) and host_pia.py
   (HostPeerProtocol), line for line. */
#include <string.h>

#include "gift_int.h"

#define PROTO_NET 1
#define PROTO_RTT 3
#define PROTO_RELIABLE 10
#define PROTO_SESSION 13
#define HOST_VAR 0x00C6
#define SESSION_VAR 0x0001
#define PIA_PORT 12345
#define NET_RETRY_US 500000
#define SESSION_ACCEPT_RETRY_US 250000
#define HOST_RTT_PERIOD_US 315000
#define QUIET_GATE_US 250000
#define QUIET_RETRANSMIT_US 1000000
#define RELIABLE_BATCH_MAX 9
#define COMPRESS_MIN 62
#define APPLICATION_HEADER_SIZE 0x5C
#define DATAGRAM_MAX 1472

static const uint8_t PIA_MAGIC[4] = {0x32, 0xab, 0x98, 0x64};

/* ldn_constant_id: the MAC reordered, then two zeros */
static void constant_id(const uint8_t mac[6], uint8_t out[8])
{
    const uint8_t id[8] = {mac[2], mac[4], mac[5], mac[3], mac[1], mac[0], 0, 0};
    memcpy(out, id, 8);
}

static uint64_t take_nonce(gift_host_t *h)
{
    if (h->image->flags & 1) return h->pia.nonce++;
    return (uint64_t)h->platform->random(h->platform->context) << 32 | h->platform->random(h->platform->context);
}

/* A zstd frame of one raw block, with the console's window descriptor (28b52ffd 00 18). */
static size_t zstd_raw(const uint8_t *in, size_t length, uint8_t *out)
{
    static const uint8_t prefix[6] = {0x28, 0xb5, 0x2f, 0xfd, 0x00, 0x18};
    memmove(out + 9, in, length);   /* `out` may be `in` */
    memcpy(out, prefix, 6);
    const uint32_t block = (uint32_t)(length << 3) | 1u;   /* last block, raw */
    out[6] = (uint8_t)block;
    out[7] = (uint8_t)(block >> 8);
    out[8] = (uint8_t)(block >> 16);
    return 9 + length;
}

typedef struct {
    uint8_t proto;
    const uint8_t *payload;
    uint16_t length;
    int16_t msgflags;            /* -1: none */
} msg_t;

/* build_messages: the messages, compressed or not, a footer, 0xFF padding, AES-GCM. */
static size_t build_datagram(gift_host_t *h, const msg_t *msgs, size_t count, uint16_t dst, uint16_t src,
                             uint16_t pktid, bool compress, bool auto_compress, bool establishing,
                             int32_t footer_var, uint8_t *out)
{
    uint8_t *body = h->scratch;
    size_t n = 0;
    for (size_t i = 0; i < count; ++i) {
        const msg_t *m = &msgs[i];
        if (n + 5 + m->length > DATAGRAM_MAX - 64) return 0;
        body[n++] = (uint8_t)(0x06 | (m->msgflags >= 0 ? 1 : 0));
        if (m->msgflags >= 0) body[n++] = (uint8_t)m->msgflags;
        pb16(body + n, m->length);
        n += 2;
        body[n++] = m->proto;
        memcpy(body + n, m->payload, m->length);
        n += m->length;
    }
    const bool zip = compress || (auto_compress && n >= COMPRESS_MIN);
    if (zip) n = zstd_raw(body, n, body);
    uint8_t footer = 0;
    if (footer_var >= 0) {
        pb16(body + n, (uint16_t)footer_var);
        n += 2;
        footer = 2;
    }
    const uint8_t pad = (uint8_t)((16 - n % 16) % 16);
    memset(body + n, 0xff, pad);
    n += pad;
    memcpy(out, PIA_MAGIC, 4);
    out[4] = 0x90;
    out[5] = (uint8_t)(pad << 4 | (zip ? 1 : 0) | (establishing ? 2 : 0));
    pb16(out + 6, dst);
    pb16(out + 8, src);
    pb16(out + 10, pktid);
    out[12] = footer;
    const uint64_t nonce = take_nonce(h);
    pb32(out + 13, (uint32_t)(nonce >> 32));
    pb32(out + 17, (uint32_t)nonce);
    uint8_t iv[12];
    pb32(iv, h->image->pia_network_id ^ gb32(h->image->host_ip));
    memcpy(iv + 4, out + 13, 8);
    if (h->platform->gcm_seal(h->image->session_key, iv, NULL, 0, body, out + 29, n, out + 21, 8)) return 0;
    return 29 + n;
}

static size_t build_one(gift_host_t *h, uint8_t proto, const uint8_t *payload, uint16_t length, uint16_t dst,
                        uint16_t pktid, bool compress, bool establishing, int32_t footer_var, uint8_t *out)
{
    const msg_t m = {proto, payload, length, -1};
    return build_datagram(h, &m, 1, dst, HOST_VAR, pktid, compress, false, establishing, footer_var, out);
}

static void send_to(gift_host_t *h, const uint8_t ip[4], const uint8_t *datagram, size_t length)
{
    if (length) gift_send_udp(h, ip, datagram, length);
}

static void broadcast_ip(const gift_host_t *h, uint8_t out[4])
{
    memcpy(out, h->image->host_ip, 3);
    out[3] = 255;
}

/* ---- pia_connect.py codecs ---- */

static size_t net_station(uint8_t *p, const uint8_t *ip, uint8_t rank)
{
    memset(p, 0, 22);
    p[1] = rank;
    if (ip) {
        memcpy(p + 4, ip, 4);
        pb16(p + 20, PIA_PORT);
    }
    return 22;
}

/* build_net_conn_request, Pia 6.39 (22-byte stations) */
static size_t net_conn_request(gift_host_t *h, uint8_t *p)
{
    const uint8_t max = h->image->advert->max_stations;
    uint8_t *b = p + 4;
    pb32(b, h->pia.net_sequence);
    pb16(b + 4, HOST_VAR);
    constant_id(h->image->advert->bssid, b + 6);
    memset(b + 14, 0, 4);
    pb32(b + 18, h->image->pia_network_id);
    b[22] = 1;
    pb16(b + 23, max);
    b[25] = 0;
    size_t n = 26;
    n += net_station(b + n, h->image->host_ip, 0);
    uint8_t ranks = 1;
    if (h->station.seated) n += net_station(b + n, h->station.ip, ranks++);
    for (; ranks < max; ++ranks) n += net_station(b + n, NULL, 0xFF);
    p[0] = 0x01;
    p[1] = 0x11;
    pb16(p + 2, (uint16_t)(max * 22));
    return 4 + n;
}

static size_t net_property_update(gift_host_t *h, uint8_t *p)
{
    const uint8_t *app = h->image->app_data_active;
    const uint16_t length = h->image->app_data_active_length;
    const uint16_t system = length < APPLICATION_HEADER_SIZE ? length : APPLICATION_HEADER_SIZE;
    uint8_t *b = p + 4;
    pb32(b, 1);
    memset(b + 4, 0, 4);
    pb32(b + 8, h->image->pia_network_id);
    pb16(b + 12, (uint16_t)(1 + (h->station.seated ? 1 : 0)));
    pb16(b + 14, h->image->advert->max_stations);
    memset(b + 16, 0, 6);
    pb16(b + 22, gl16(h->image->auth_network_id + 10));   /* the scene id */
    b[24] = 1;
    b[25] = 1;
    pb32(b + 26, system);
    pb32(b + 30, (uint32_t)(length - system));
    memcpy(b + 34, app, length);
    p[0] = 0x01;
    p[1] = 0x50;
    pb16(p + 2, length);
    return 4 + 34 + length;
}

static bool parse_join(const uint8_t *p, size_t n, pia_join_t *j)
{
    memset(j, 0, sizeof(*j));
    if (n < 2 || p[0] != 0) return false;
    const uint8_t count = p[1];
    size_t at = 2;
    if (at + count * 2u + 2 + 4 + 8 + 2 + 2 + 32 + 8 + 2 + 2 > n || count > 16) return false;
    j->protocol_count = count;
    memcpy(j->protocols, p + at, count * 2u);
    at += count * 2u + 2 + 4;
    memcpy(j->source_constant, p + at, 8); at += 8;
    j->source_var = gb16(p + at); at += 2;
    at += 2;
    memcpy(j->token, p + at, 32); at += 32;
    memcpy(j->destination_constant, p + at, 8); at += 8;
    j->destination_var = gb16(p + at); at += 2;
    j->num_players = p[at];
    j->num_participants = p[at + 1];
    at += 2;
    if (at >= n || p[at] != 0) return false;
    ++at;
    if (at + 6 > n) return false;
    memcpy(j->ip, p + at, 4); at += 4;
    j->port = gb16(p + at); at += 2;
    if (j->num_players > 2) return false;
    for (uint8_t i = 0; i < j->num_players; ++i) {
        if (at + 21 > n) return false;
        const uint32_t name = gb32(p + at + 16);
        if (name > 40 || at + 21 + name > n) return false;
        memcpy(j->players[i], p + at, 21 + name);
        j->player_length[i] = (uint8_t)(21 + name);
        at += 21 + name;
    }
    return at == n;
}

static size_t session_station(uint8_t *p, const uint8_t constant[8], uint16_t var, const uint8_t ip[4],
                              uint16_t port, uint8_t index, uint16_t join_order, const uint8_t token[32],
                              uint8_t players, uint8_t participants)
{
    memcpy(p, constant, 8);
    pb16(p + 8, var);
    memcpy(p + 10, ip, 4);
    pb16(p + 14, port);
    p[16] = index;
    pb16(p + 17, join_order);
    p[19] = p[20] = 0;
    memcpy(p + 21, token, 32);
    p[53] = players;
    p[54] = participants;
    p[55] = p[56] = 0;
    return 57;
}

/* build_session_update: sequence id 1, update sequence 0, the host first */
static size_t session_update(gift_host_t *h, uint8_t *p)
{
    const gift_image_t *im = h->image;
    const pia_join_t *j = &h->pia.join;
    uint8_t host_constant[8];
    constant_id(im->advert->bssid, host_constant);
    static const uint8_t head[7] = {0x05, 0x00, 0x00, 0x01, 0x00, 0x00, 0x03};
    memcpy(p, head, 7);
    size_t n = 7;
    memcpy(p + n, host_constant, 8); n += 8;
    pb16(p + n, HOST_VAR); n += 2;
    p[n++] = 2;
    p[n++] = 0;
    pb16(p + n, 1); n += 2;
    pb16(p + n, 0); n += 2;
    memset(p + n, 0, 4); n += 4;
    static const uint8_t zero_token[32] = {0};
    n += session_station(p + n, host_constant, HOST_VAR, im->host_ip, PIA_PORT, 0, 0, zero_token, 1, 1);
    memcpy(p + n, im->host_player_id, 16);
    pb32(p + n + 16, im->host_name_length);
    p[n + 20] = 1;
    memcpy(p + n + 21, im->host_name, im->host_name_length);
    n += 21u + im->host_name_length;
    n += session_station(p + n, j->source_constant, j->source_var, j->ip, j->port, 1, 1, j->token,
                         j->num_players, j->num_participants);
    for (uint8_t i = 0; i < j->num_players; ++i) {
        memcpy(p + n, j->players[i], j->player_length[i]);
        n += j->player_length[i];
    }
    return n;
}

static size_t session_join_response(gift_host_t *h, uint8_t *p)
{
    const pia_join_t *j = &h->pia.join;
    uint8_t version = 7;
    for (uint8_t i = 0; i < j->protocol_count; ++i)
        if (j->protocols[i][0] == PROTO_SESSION) version = j->protocols[i][1];
    p[0] = 2;
    p[1] = PROTO_SESSION;
    p[2] = version;
    p[3] = 1;
    memset(p + 4, 0, 4);
    pb32(p + 8, h->platform->random(h->platform->context));
    constant_id(h->image->advert->bssid, p + 12);
    pb16(p + 20, j->destination_var);
    memcpy(p + 22, j->source_constant, 8);
    pb16(p + 30, j->source_var);
    p[32] = 1;
    pb16(p + 33, 1);
    p[35] = p[36] = 0;
    return 37;
}

/* ---- HostPeerProtocol ---- */

void pia_reset(gift_host_t *h)
{
    pia_t *p = &h->pia;
    memset(p, 0, sizeof(*p));
    p->net_sequence = 2;
    p->session_packet_id = 2;
    p->reliable_packet_id = 2;
    p->rtt_systime = 0x10000;
    p->nonce = (uint64_t)h->platform->random(h->platform->context) << 32 | h->platform->random(h->platform->context);
}

void pia_participant_joined(gift_host_t *h)
{
    pia_t *p = &h->pia;
    if (p->joined) return;
    p->joined = true;
    p->next_net_us = 0;
}

static void send_session_acceptance(gift_host_t *h)
{
    pia_t *p = &h->pia;
    uint8_t message[512];
    uint8_t *response = h->frame;
    /* Native allocates the response's nonce first but transmits the update first. */
    size_t n = session_join_response(h, message);
    const size_t rlen = build_one(h, PROTO_SESSION, message, (uint16_t)n, p->guest_var, 1, false, false,
                                  p->guest_var, response);
    static uint8_t update[DATAGRAM_MAX];
    n = session_update(h, message);
    const size_t ulen = build_one(h, PROTO_SESSION, message, (uint16_t)n, SESSION_VAR, 1, true, false,
                                  p->guest_var, update);
    uint8_t bcast[4];
    broadcast_ip(h, bcast);
    if (h->image->flags & 2) {
        send_to(h, p->join.ip, response, rlen);
        send_to(h, bcast, update, ulen);
        send_to(h, p->join.ip, update, ulen);
    } else {
        send_to(h, bcast, update, ulen);
        send_to(h, p->join.ip, update, ulen);
        send_to(h, p->join.ip, response, rlen);
    }
}

static void answer_leave(gift_host_t *h, uint16_t src, const uint8_t *payload, size_t n, const uint8_t ip[4])
{
    pia_t *p = &h->pia;
    if (!p->have_join || src != p->guest_var || n < 15 || gb16(payload + 13) != p->guest_var) return;
    if ((n != 0x16 && n != 0x22) || payload[0] != 3) return;
    uint8_t response[15];
    response[0] = 4;
    pb32(response + 1, h->platform->random(h->platform->context));
    memcpy(response + 5, payload + 5, 10);
    const size_t length = build_one(h, PROTO_SESSION, response, 15, p->guest_var, p->reliable_packet_id, false,
                                    false, p->guest_var, h->frame);
    p->reliable_packet_id = p->reliable_packet_id < 0xFFFF ? (uint16_t)(p->reliable_packet_id + 1) : 1;
    send_to(h, ip, h->frame, length);
}

static void receive_session(gift_host_t *h, uint16_t src, const uint8_t *payload, size_t n, const uint8_t ip[4])
{
    pia_t *p = &h->pia;
    if (!n) return;
    if (payload[0] == 0) {
        pia_join_t join;
        if (!parse_join(payload, n, &join)) return;
        uint8_t expected[8];
        constant_id(h->image->advert->bssid, expected);
        if (memcmp(join.destination_constant, expected, 8) || join.destination_var != HOST_VAR ||
            join.source_var != src || memcmp(join.ip, ip, 4))
            return;
        p->session_join_seen = true;
        p->join = join;
        p->have_join = true;
        p->guest_var = join.source_var;
        memcpy(p->guest_ip, ip, 4);
        if (!p->finalized) {
            send_session_acceptance(h);
            p->accept_due = true;
            p->next_accept_us = h->now_us + SESSION_ACCEPT_RETRY_US;
        }
    } else if (payload[0] == 6 && !p->finalized) {
        p->finalized = true;
        p->accept_due = false;
        p->tick_due = true;
        p->next_tick_us = h->now_us;
    } else if (payload[0] == 3) {
        answer_leave(h, src, payload, n, ip);
    }
}

static void send_rtt(gift_host_t *h, const uint8_t *payload, const uint8_t ip[4])
{
    pia_t *p = &h->pia;
    const size_t length = build_one(h, PROTO_RTT, payload, 21, SESSION_VAR, p->session_packet_id, false, false,
                                    p->guest_var, h->frame);
    p->session_packet_id = (uint16_t)(p->session_packet_id + 1) ? (uint16_t)(p->session_packet_id + 1) : 1;
    send_to(h, ip, h->frame, length);
}

static void receive_rtt(gift_host_t *h, const uint8_t *payload, size_t n, const uint8_t ip[4])
{
    pia_t *p = &h->pia;
    if (n < 16 || !p->finalized || !p->have_join) return;
    if (payload[0] == 0) {
        memset(p->rtt_template, 0, 21);
        memcpy(p->rtt_template, payload, n < 21 ? n : 21);
        p->have_rtt_template = true;
        uint8_t response[21];
        memcpy(response, p->rtt_template, 21);
        response[0] = 1;
        send_rtt(h, response, ip);
        if (!p->rtt_due_set) {
            p->rtt_due_set = true;
            p->next_rtt_us = 0;
        }
    } else if (payload[0] == 1) {
        uint64_t systime = 0;
        for (int i = 7; i >= 0; --i) systime = systime << 8 | payload[8 + i];
        for (uint8_t i = 0; i < p->rtt_pending_count; ++i) {
            if (p->rtt_pending_systime[i] != systime) continue;
            rel_note_rtt(&h->rel, (float)(h->now_us - p->rtt_pending_us[i]) / 1000.0f);
            p->rtt_pending_systime[i] = p->rtt_pending_systime[--p->rtt_pending_count];
            p->rtt_pending_us[i] = p->rtt_pending_us[p->rtt_pending_count];
            break;
        }
    }
}

/* decode_datagram: AES-GCM, padding, footer, zstd, message tiling; then each message. */
void pia_receive(gift_host_t *h, const uint8_t *d, size_t length, const uint8_t src_ip[4])
{
    pia_t *p = &h->pia;
    p->last_rx_us = h->now_us;
    p->have_rx = true;
    if (!p->joined || length < 29 || memcmp(d, PIA_MAGIC, 4) || length - 29 > sizeof(h->scratch)) return;
    uint8_t iv[12];
    pb32(iv, h->image->pia_network_id ^ gb32(src_ip));
    memcpy(iv + 4, d + 13, 8);
    uint8_t *plain = h->scratch;
    size_t n = length - 29;
    if (h->platform->gcm_open(h->image->session_key, iv, NULL, 0, d + 29, plain, n, d + 21, 8)) return;
    const uint8_t pad = d[5] >> 4, footer = d[12];
    if (pad) {
        if (n < pad) return;
        for (size_t i = n - pad; i < n; ++i)
            if (plain[i] != 0xff) return;
        n -= pad;
    }
    if (footer) {
        if (n < footer) return;
        n -= footer;
    }
    if (d[5] & 1) {
        if (n < 4 || plain[0] != 0x28 || plain[1] != 0xb5 || plain[2] != 0x2f || plain[3] != 0xfd) return;
        const size_t unzipped = gift_zstd_decompress(plain, n, h->frame, sizeof(h->frame));
        if (unzipped == SIZE_MAX) return;
        memcpy(plain, h->frame, unzipped);
        n = unzipped;
    }
    /* parse_messages: a field whose presence bit is clear inherits the previous message's */
    const uint16_t src = gb16(d + 8);
    msg_t msgs[24];
    size_t count = 0, i = 0;
    int size = -1;
    uint8_t proto = 0;
    while (i < n && count < 24) {
        const uint8_t fl = plain[i];
        if (fl == 0xff || (fl & 0xE0)) break;
        if (fl == 0 && size < 0) break;
        size_t j = i + 1;
        if (fl & 1) { if (j >= n) break; ++j; }
        if (fl & 2) { if (j + 2 > n) break; size = gb16(plain + j); j += 2; }
        if (fl & 4) { if (j >= n) break; proto = plain[j++]; }
        if (fl & 8) { if (j + 1 > n) break; ++j; }
        if (fl & 0x10) { if (j + 1 > n) break; ++j; }
        if (size < 0 || j + (size_t)size > n) break;
        msgs[count++] = (msg_t){proto, plain + j, (uint16_t)size, -1};
        i = j + (size_t)size;
    }
    if (!count || i != n) return;
    /* The messages point into `scratch`, which a reply rebuilds: keep them in `frame` instead. */
    uint8_t copy[sizeof(h->frame)];
    memcpy(copy, plain, n);
    for (size_t k = 0; k < count; ++k) msgs[k].payload = copy + (msgs[k].payload - plain);
    for (size_t k = 0; k < count; ++k) {
        const msg_t *m = &msgs[k];
        if (m->proto == PROTO_NET) {
            if (m->length >= 4 && m->payload[1] == 0x12) p->net_acked = true;
        } else if (m->proto == PROTO_SESSION) {
            receive_session(h, src, m->payload, m->length, src_ip);
        } else if (m->proto == PROTO_RTT) {
            receive_rtt(h, m->payload, m->length, src_ip);
        } else if (m->proto == PROTO_RELIABLE && p->finalized) {
            session_receive(h, m->payload, m->length, (uint32_t)(h->now_us / 1000));
        }
    }
}

/* _apply_carry_forward: unacked data frames of the last few datagrams ride along again. */
static size_t carry_forward(gift_host_t *h, rel_emit_t *out, size_t n)
{
    pia_t *p = &h->pia;
    rel_emit_t carried[REL_EMIT_MAX];
    size_t c = 0;
    uint16_t have[REL_EMIT_MAX * (PIA_CARRY_DEPTH + 1)];
    size_t have_n = 0;
    for (size_t i = 0; i < n; ++i) have[have_n++] = out[i].seq;
    for (int list = (int)p->carry_lists - 1; list >= 0; --list) {
        for (uint8_t i = 0; i < p->carry_count[list] && c < REL_EMIT_MAX; ++i) {
            const pia_carried_t *it = &p->carry[list][i];
            bool seen = false;
            for (size_t k = 0; k < have_n; ++k) seen |= have[k] == it->seq;
            if (seen || !rel_entry_live(&h->rel, it->seq)) continue;
            have[have_n++] = it->seq;
            uint8_t length;
            const uint8_t *data = rel_entry_data(&h->rel, it->seq, &length);
            carried[c++] = (rel_emit_t){it->seq, it->ack, it->flags, it->retransmitted, data, length};
        }
    }
    /* Remember this datagram's data frames, the last PIA_CARRY_DEPTH datagrams' only. */
    if (p->carry_lists == PIA_CARRY_DEPTH) {
        memmove(p->carry[0], p->carry[1], sizeof(p->carry[0]) * (PIA_CARRY_DEPTH - 1));
        memmove(p->carry_count, p->carry_count + 1, PIA_CARRY_DEPTH - 1);
        --p->carry_lists;
    }
    uint8_t kept = 0;
    for (size_t i = 0; i < n; ++i)
        if (out[i].flags != 0)
            p->carry[p->carry_lists][kept++] = (pia_carried_t){out[i].seq, out[i].ack, out[i].flags,
                                                               out[i].retransmitted};
    p->carry_count[p->carry_lists++] = kept;
    if (!c) return n;
    uint16_t low = have[0];
    for (size_t k = 1; k < have_n; ++k) if (have[k] < low) low = have[k];
    for (size_t a = 1; a < c; ++a)
        for (size_t b = a; b > 0 && (uint16_t)(carried[b - 1].seq - low) > (uint16_t)(carried[b].seq - low); --b) {
            const rel_emit_t t = carried[b]; carried[b] = carried[b - 1]; carried[b - 1] = t;
        }
    if (c + n > REL_EMIT_MAX) c = REL_EMIT_MAX - n;
    memmove(out + c, out, n * sizeof(*out));
    memcpy(out, carried, c * sizeof(*out));
    return c + n;
}

static void send_reliable(gift_host_t *h, rel_emit_t *out, size_t n)
{
    pia_t *p = &h->pia;
    if (!n || !p->have_join) return;
    const uint64_t now = h->now_us;
    if (p->have_rx && now - p->last_rx_us > QUIET_GATE_US) {
        rel_emit_t fresh[REL_EMIT_MAX];
        size_t f = 0;
        bool any_old = false;
        for (size_t i = 0; i < n; ++i) any_old |= out[i].retransmitted;
        if (any_old && now - p->last_quiet_retransmit_us >= QUIET_RETRANSMIT_US) {
            p->last_quiet_retransmit_us = now;
            for (size_t i = 0; i < n; ++i)
                if (out[i].retransmitted) { fresh[f++] = out[i]; break; }
        }
        for (size_t i = 0; i < n; ++i)
            if (!out[i].retransmitted) fresh[f++] = out[i];
        memcpy(out, fresh, f * sizeof(*out));
        n = f;
        if (!n) return;
    } else {
        n = carry_forward(h, out, n);
    }
    /* reliable_output_batches: an ack or a retransmission ends its batch */
    uint8_t wire[REL_EMIT_MAX][8 + REL_OUT_MAX];
    size_t start = 0;
    while (start < n) {
        size_t end = start;
        while (end < n && end - start < RELIABLE_BATCH_MAX) {
            const bool flagged = out[end].flags == 0 || out[end].retransmitted;
            ++end;
            if (flagged) break;
        }
        msg_t msgs[RELIABLE_BATCH_MAX];
        for (size_t i = start; i < end; ++i) {
            const rel_emit_t *e = &out[i];
            uint8_t *w = wire[i];
            w[0] = e->flags;
            pb16(w + 1, e->length);
            pb16(w + 3, e->seq);
            pb16(w + 5, e->ack);
            w[7] = 0;
            memcpy(w + 8, e->data, e->length);
            msgs[i - start] = (msg_t){PROTO_RELIABLE, w, (uint16_t)(8 + e->length),
                                      (int16_t)(e->flags == 0 ? 0x40 : e->retransmitted ? 0x20 : -1)};
        }
        const size_t length = build_datagram(h, msgs, end - start, p->guest_var, HOST_VAR, p->reliable_packet_id,
                                             false, true, false, p->guest_var, h->frame);
        send_to(h, p->guest_ip, h->frame, length);
        p->reliable_packet_id = p->reliable_packet_id < 0xFFFF ? (uint16_t)(p->reliable_packet_id + 1) : 1;
        start = end;
    }
}

uint64_t pia_tick(gift_host_t *h)
{
    pia_t *p = &h->pia;
    const uint64_t now = h->now_us;
    uint8_t message[600];
    if (p->joined && !p->net_acked && now >= p->next_net_us) {
        const size_t n = net_conn_request(h, message);
        const size_t length = build_one(h, PROTO_NET, message, (uint16_t)n, 0, 0, true, true, -1, h->frame);
        uint8_t bcast[4];
        broadcast_ip(h, bcast);
        send_to(h, bcast, h->frame, length);
        if (h->station.seated) send_to(h, h->station.ip, h->frame, length);
        p->next_net_us = now + NET_RETRY_US;
    }
    if (p->have_join && !p->finalized && p->accept_due && now >= p->next_accept_us) {
        send_session_acceptance(h);
        p->next_accept_us = now + SESSION_ACCEPT_RETRY_US;
    }
    if (p->finalized && p->have_rtt_template && p->have_join && p->rtt_due_set && now >= p->next_rtt_us) {
        ++p->rtt_systime;
        uint8_t request[21];
        memcpy(request, p->rtt_template, 21);
        request[0] = 0;
        for (int i = 0; i < 8; ++i) request[8 + i] = (uint8_t)(p->rtt_systime >> (8 * i));
        send_rtt(h, request, p->guest_ip);
        if (p->rtt_pending_count == 8) {
            memmove(p->rtt_pending_systime, p->rtt_pending_systime + 1, 7 * sizeof(uint64_t));
            memmove(p->rtt_pending_us, p->rtt_pending_us + 1, 7 * sizeof(uint64_t));
            --p->rtt_pending_count;
        }
        p->rtt_pending_systime[p->rtt_pending_count] = p->rtt_systime;
        p->rtt_pending_us[p->rtt_pending_count++] = now;
        p->next_rtt_us = now + HOST_RTT_PERIOD_US;
    }
    if (p->finalized && p->tick_due && now >= p->next_tick_us) {
        rel_emit_t out[REL_EMIT_MAX];
        const size_t n = session_tick(h, (uint32_t)(now / 1000), out);
        send_reliable(h, out, n);
        p->next_tick_us = now + h->image->tick_us;
    }
    if (h->mg.linked && !p->property_started) {
        p->property_started = true;
        p->next_property_us = 0;
        gift_note_app_active(h);
    }
    if (p->property_started && now >= p->next_property_us) {
        const size_t n = net_property_update(h, message);
        const size_t length = build_one(h, PROTO_NET, message, (uint16_t)n, 0, 0, true, true, -1, h->frame);
        send_to(h, p->guest_ip, h->frame, length);
        p->next_property_us = now + NET_RETRY_US;
    }
    uint64_t next = now + 50000;   /* HOST_CONTROL_POLL_SECONDS */
    if (p->joined && !p->net_acked && p->next_net_us < next) next = p->next_net_us;
    if (p->have_join && !p->finalized && p->accept_due && p->next_accept_us < next) next = p->next_accept_us;
    if (p->finalized && p->rtt_due_set && p->next_rtt_us < next) next = p->next_rtt_us;
    if (p->finalized && p->tick_due && p->next_tick_us < next) next = p->next_tick_us;
    if (p->property_started && p->next_property_us < next) next = p->next_property_us;
    return next;
}
