/* The link under the Mystery Gift: pokeldn/ldn/reliable.py (HostReliableSession, ReliableLink),
   pokeldn/gba/ni.py, rfu.py and rfu_leader.py (RFULeader, ChildEcho), and
   pokeldn/frlg/link/host_session.py (HostSession), line for line. */
#include <string.h>

#include "gift_int.h"

/* reliable.py */
#define RTO_BASE_MS 33
#define RTO_RTT_FACTOR 1.4f
#define RTO_BOOTSTRAP_MS 200
#define FAST_RETX_MIN_MS 25
#define FLAGS_GBA 0x07
#define FLAGS_INIT 0x0f
#define FLAGS_CTRL 0x00
/* host_session.py */
#define HOST_RTX_LIMIT 2
#define HOST_OUTSTANDING_MAX 6
/* rfu.py, gbaframe.py, ni.py */
#define GBA_MARKER 0x57
#define TYPE_T 0x54
#define TYPE_K 0x4B
#define TYPE_C 0x43
#define TYPE_A 0x41
#define TYPE_D 0x44
#define TYPE_G 0x47
#define LCOM_NULL 0
#define LCOM_NI_START 1
#define LCOM_NI 2
#define LCOM_NI_END 3
#define LCOM_UNI 4
#define BM_SLOT 1
#define JOIN_STATUS_OK 5
#define READY_CLOSE_LINK 0x5F00

#define SLOT(seq) ((uint16_t)(seq) % REL_WINDOW)
#define BIT(map, seq) (((map)[SLOT(seq) >> 3] >> (SLOT(seq) & 7)) & 1)
#define SET(map, seq) ((map)[SLOT(seq) >> 3] |= (uint8_t)(1 << (SLOT(seq) & 7)))
#define CLEAR(map, seq) ((map)[SLOT(seq) >> 3] &= (uint8_t)~(1 << (SLOT(seq) & 7)))

static bool seq_lt(uint16_t a, uint16_t b)
{
    const uint16_t d = (uint16_t)(b - a);
    return d != 0 && d < 0x8000;
}

/* ---- ReliableLink ---- */

void rel_reset(rel_t *r)
{
    memset(r, 0, sizeof(*r));
    r->out_seq = r->window_lo = r->recv_next = r->deliver_next = REL_START;
    r->peer_gap = -1;
}

static uint16_t inflight(const rel_t *r) { return (uint16_t)(r->out_seq - r->window_lo); }

bool rel_entry_live(const rel_t *r, uint16_t seq)
{
    return (uint16_t)(seq - r->window_lo) < inflight(r) && !r->out[SLOT(seq)].acked;
}

const uint8_t *rel_entry_data(const rel_t *r, uint16_t seq, uint8_t *length)
{
    *length = r->out[SLOT(seq)].length;
    return r->out[SLOT(seq)].data;
}

uint16_t rel_outstanding(const rel_t *r)
{
    uint16_t n = 0;
    for (uint16_t i = 0; i < inflight(r); ++i)
        if (!r->out[SLOT(r->window_lo + i)].acked) ++n;
    return n;
}

static uint16_t send_low(const rel_t *r) { return inflight(r) ? r->window_lo : r->out_seq; }

static uint16_t queue(rel_t *r, const uint8_t *data, uint8_t length, uint8_t flags, uint32_t now_ms)
{
    const uint16_t seq = r->out_seq++;
    rel_out_t *e = &r->out[SLOT(seq)];
    memcpy(e->data, data, length);
    e->length = length;
    e->flags = flags;
    e->resends = 0;
    e->acked = false;
    e->last_tx_ms = now_ms;
    return seq;
}

void rel_note_rtt(rel_t *r, float rtt_ms)
{
    if (rtt_ms < 0) return;
    if (r->rtt_count == REL_RTT_WINDOW) {
        memmove(r->rtt, r->rtt + 1, sizeof(float) * (REL_RTT_WINDOW - 1));
        --r->rtt_count;
    }
    r->rtt[r->rtt_count++] = rtt_ms;
}

static float median_rtt(const rel_t *r)
{
    float s[REL_RTT_WINDOW];
    memcpy(s, r->rtt, sizeof(float) * r->rtt_count);
    for (int i = 1; i < r->rtt_count; ++i)
        for (int j = i; j > 0 && s[j - 1] > s[j]; --j) {
            const float t = s[j]; s[j] = s[j - 1]; s[j - 1] = t;
        }
    return s[r->rtt_count / 2];
}

static float rto(const rel_t *r)
{
    return r->rtt_count ? RTO_BASE_MS + RTO_RTT_FACTOR * median_rtt(r) : RTO_BOOTSTRAP_MS;
}

static void on_ack(rel_t *r, uint16_t ack_id, const uint8_t mask[16], uint32_t now_ms)
{
    bool any = false;
    for (int i = 0; i < 16; ++i) any |= mask[i] != 0;
    for (uint16_t k = 0; k < inflight(r); ++k) {
        const uint16_t seq = (uint16_t)(r->window_lo + k);
        rel_out_t *e = &r->out[SLOT(seq)];
        bool arrived = seq_lt(seq, ack_id);
        if (!arrived && any) {
            /* bit i is ack_id + i + 1 (MASK_ORIGIN_OFFSET) */
            const uint16_t i = (uint16_t)(seq - ack_id - 1);
            arrived = i < 128 && ((mask[i >> 3] >> (i & 7)) & 1);
        }
        if (arrived && !e->acked) {
            if (e->resends == 0) rel_note_rtt(r, (float)(int32_t)(now_ms - e->last_tx_ms));
            e->acked = true;
        }
    }
    while (inflight(r) && r->out[SLOT(r->window_lo)].acked) ++r->window_lo;
    const bool held = (uint16_t)(ack_id - r->window_lo) < inflight(r);
    if (any && held && !r->out[SLOT(ack_id)].acked) {
        if (r->peer_gap == ack_id) ++r->gap_nacks;
        else { r->peer_gap = ack_id; r->gap_nacks = 1; }
    } else {
        r->peer_gap = -1;
        r->gap_nacks = 0;
    }
}

static size_t due_retransmits(rel_t *r, uint32_t now_ms, size_t limit, rel_emit_t *out)
{
    const float base = rto(r);
    const float fast_gap = r->rtt_count ? (median_rtt(r) > FAST_RETX_MIN_MS ? median_rtt(r) : FAST_RETX_MIN_MS)
                                        : FAST_RETX_MIN_MS;
    size_t n = 0;
    for (uint16_t k = 0; k < inflight(r); ++k) {
        const uint16_t seq = (uint16_t)(r->window_lo + k);
        rel_out_t *e = &r->out[SLOT(seq)];
        if (e->acked) continue;
        const uint32_t since = now_ms - e->last_tx_ms;
        bool due;
        if (r->peer_gap == seq && r->gap_nacks >= 1 && (e->resends == 0 || (float)since >= fast_gap)) {
            due = true;
            r->gap_nacks = 0;
        } else {
            due = (float)since >= base;
        }
        if (due) {
            e->last_tx_ms = now_ms;
            ++e->resends;
            out[n++] = (rel_emit_t){seq, 0, e->flags, true, e->data, e->length};
            if (n >= limit) break;
        } else {
            break;
        }
    }
    for (size_t i = 0; i < n; ++i) out[i].ack = send_low(r);
    return n;
}

static void note_received(rel_t *r, uint16_t seq)
{
    if (seq == r->recv_next) {
        ++r->recv_next;
        while (BIT(r->ooo, r->recv_next)) {
            CLEAR(r->ooo, r->recv_next);
            ++r->recv_next;
        }
    } else if (seq_lt(r->recv_next, seq) && (uint16_t)(seq - r->recv_next) < REL_WINDOW) {
        SET(r->ooo, seq);
    }
}

static bool any_ooo(const rel_t *r)
{
    for (int i = 0; i < REL_WINDOW / 8; ++i)
        if (r->ooo[i]) return true;
    return false;
}

static void ack_payload(rel_t *r)
{
    uint8_t *p = r->ack_frame;
    memset(p, 0, 20);
    p[1] = 1;
    pb16(p + 2, r->recv_next);
    for (uint16_t d = 1; d < REL_WINDOW; ++d)
        if (BIT(r->ooo, r->recv_next + d)) p[4 + ((d - 1) >> 3)] |= (uint8_t)(1 << ((d - 1) & 7));
}

static rel_emit_t emission(rel_t *r, uint16_t seq)
{
    const rel_out_t *e = &r->out[SLOT(seq)];
    return (rel_emit_t){seq, send_low(r), e->flags, false, e->data, e->length};
}

static rel_emit_t rel_send(rel_t *r, const uint8_t *data, uint8_t length, uint32_t now_ms)
{
    return emission(r, queue(r, data, length, FLAGS_GBA, now_ms));
}

static rel_emit_t rel_open(rel_t *r, const uint8_t *data, uint8_t length, uint32_t now_ms)
{
    r->local_opened = true;
    return emission(r, queue(r, data, length, FLAGS_GBA | FLAGS_INIT, now_ms));
}

static size_t rel_poll(rel_t *r, uint32_t now_ms, rel_emit_t *out)
{
    size_t n = due_retransmits(r, now_ms, HOST_RTX_LIMIT, out);
    const bool ack_due = r->ack_due_set && (int32_t)(now_ms - r->next_ack_ms) >= 0;
    if (ack_due && (r->ack_owed || any_ooo(r))) {
        ack_payload(r);
        out[n++] = (rel_emit_t){REL_START, send_low(r), FLAGS_CTRL, false, r->ack_frame, 20};
        r->ack_owed = false;
        r->ack_due_set = any_ooo(r);
        r->next_ack_ms = now_ms + RTO_BASE_MS;
    }
    return n;
}

/* ---- gbaframe.py ---- */

static uint8_t gba_frame(uint8_t *out, uint8_t type, const uint8_t *body, uint8_t length)
{
    out[0] = GBA_MARKER;
    out[1] = type;
    pl16(out + 2, length);
    memcpy(out + 4, body, length);
    return (uint8_t)(4 + length);
}

static void rfu_push(rfu_t *r, const uint8_t *frame, uint8_t length)
{
    if (r->pending_count == RFU_PENDING_MAX) return;
    const uint8_t i = (uint8_t)((r->pending_head + r->pending_count++) % RFU_PENDING_MAX);
    memcpy(r->pending[i], frame, length);
    r->pending_length[i] = length;
}

static void push_parent_t(rfu_t *r, const uint8_t *slot, uint8_t length)
{
    uint8_t frame[RFU_FRAME_MAX] = {0};
    const uint8_t padded = (uint8_t)((length + 3) & ~3);
    pl32(frame + 4, r->ts++);
    frame[8] = length;
    memcpy(frame + 12, slot, length);
    frame[0] = GBA_MARKER;
    frame[1] = TYPE_T;
    pl16(frame + 2, (uint16_t)(8 + padded));
    rfu_push(r, frame, (uint8_t)(12 + padded));
}

static uint8_t wrap_parent_t(rfu_t *r, const uint8_t *slot, uint8_t length, uint8_t *frame)
{
    const uint8_t padded = (uint8_t)((length + 3) & ~3);
    memset(frame, 0, (size_t)(12 + padded));
    frame[0] = GBA_MARKER;
    frame[1] = TYPE_T;
    pl16(frame + 2, (uint16_t)(8 + padded));
    pl32(frame + 4, r->ts++);
    frame[8] = length;
    memcpy(frame + 12, slot, length);
    return (uint8_t)(12 + padded);
}

static void parent_llsf(uint8_t out[3], uint8_t state, uint8_t n, uint8_t phase, uint8_t ack, uint8_t size)
{
    const uint32_t f = (uint32_t)(state & 0xF) << 14 | (uint32_t)(ack & 1) << 13 | (uint32_t)(n & 3) << 11 |
                       (uint32_t)(phase & 3) << 9 | (uint32_t)(BM_SLOT & 0xF) << 18 | (size & 0x7F);
    out[0] = (uint8_t)f; out[1] = (uint8_t)(f >> 8); out[2] = (uint8_t)(f >> 16);
}

/* ---- ni.py ---- */

/* _ni_send_sequence for the parent's one-byte join status: dataType 0, payload size 5. */
static void parent_ni_sequence(rfu_t *r)
{
    const uint8_t src[1] = {JOIN_STATUS_OK};
    const uint8_t payload_size = 8 - 3;
    uint8_t header[7] = {0};
    pl16(header + 1, payload_size);
    pl32(header + 3, sizeof(src));
    r->parent_ni_count = r->parent_ni_next = 0;
    int remain = 7, off = 0;
    uint8_t n0 = 1;
    for (;;) {
        ni_item_t *it = &r->parent_ni[r->parent_ni_count++];
        it->state = LCOM_NI_START;
        it->n = n0;
        it->phase = 0;
        it->size = (uint8_t)(remain < payload_size ? remain : payload_size);
        memset(it->payload, 0, sizeof(it->payload));
        memcpy(it->payload, header + off, it->size);
        n0 = (n0 + 1) & 3;
        off += payload_size;
        remain -= payload_size;
        if (remain <= 0) break;
    }
    int now[4], nn[4] = {1, 1, 1, 1};
    for (int i = 0; i < 4; ++i) now[i] = payload_size * i;
    int phase = 0, left = sizeof(src);
    while (left > 0) {
        while (now[phase] >= (int)sizeof(src)) phase = (phase + 1) % 4;
        const int o = now[phase];
        const int size = payload_size < (int)sizeof(src) - o ? payload_size : (int)sizeof(src) - o;
        ni_item_t *it = &r->parent_ni[r->parent_ni_count++];
        it->state = LCOM_NI;
        it->n = (uint8_t)nn[phase];
        it->phase = (uint8_t)phase;
        it->size = (uint8_t)size;
        memset(it->payload, 0, sizeof(it->payload));
        memcpy(it->payload, src + o, (size_t)size);
        now[phase] += payload_size << 2;
        nn[phase] = (nn[phase] + 1) & 3;
        phase = (phase + 1) % 4;
        left -= payload_size;
    }
    r->parent_ni[r->parent_ni_count++] = (ni_item_t){LCOM_NI_END, 0, 0, 0, {0}};
    r->parent_ni[r->parent_ni_count++] = (ni_item_t){LCOM_NULL, 1, 0, 0, {0}};
}

static void ni_finalize(ni_recv_t *ni)
{
    if (ni->finalized) return;
    ni->finalized = true;
    uint16_t n = ni->buf_length;
    if (ni->have_size && ni->data_size < n) n = ni->data_size;
    memcpy(ni->game_data, ni->buf, n);
    ni->game_data_length = n;
}

/* ParentNIReceiver.on_child_ni: whether to ack it. */
static bool ni_on_child(ni_recv_t *ni, uint8_t state, uint8_t ack, uint8_t n, uint8_t phase,
                        const uint8_t *payload, uint8_t size)
{
    (void)n;
    if (ack != 0) return false;
    if (state == LCOM_NI_START) {
        for (uint8_t i = 0; i < size && ni->header_length < sizeof(ni->header); ++i)
            ni->header[ni->header_length++] = payload[i];
        if (!ni->have_size && ni->header_length >= 7) {
            const uint16_t ps = gl16(ni->header + 1);
            if (ps) ni->payload_size = (uint8_t)ps;
            ni->data_size = (uint16_t)gl32(ni->header + 3);
            ni->have_size = true;
        }
    } else if (state == LCOM_NI) {
        const uint8_t p = phase & 3;
        const uint32_t off = (uint32_t)p * ni->payload_size + (uint32_t)ni->phase_count[p] * 4 * ni->payload_size;
        if (off + size <= sizeof(ni->buf)) {
            memcpy(ni->buf + off, payload, size);
            if (off + size > ni->buf_length) ni->buf_length = (uint16_t)(off + size);
        }
        ++ni->phase_count[p];
    } else if (state == LCOM_NULL) {
        ni->complete = true;
        ni_finalize(ni);
        return false;
    }
    if (state == LCOM_NI_END) {
        ni->complete = true;
        ni_finalize(ni);
    }
    return state == LCOM_NI_START || state == LCOM_NI || state == LCOM_NI_END;
}

/* ---- rfu_leader.py ---- */

void rfu_reset(rfu_t *r, const gift_image_t *image)
{
    (void)image;
    memset(r, 0, sizeof(*r));
    r->state = RFU_WAIT_CONNECT;
    r->ts = 1;
}

static void echo_append(rfu_t *r, const uint8_t cmd[14])
{
    for (uint8_t i = 0; i < r->echo_count; ++i)
        if (!memcmp(r->echo[(r->echo_head + i) % RFU_ECHO_MAX], cmd, 14)) return;   /* coalesced */
    if (r->echo_count == RFU_ECHO_MAX) {
        r->echo_head = (uint8_t)((r->echo_head + 1) % RFU_ECHO_MAX);   /* the safety valve */
        --r->echo_count;
    }
    memcpy(r->echo[(r->echo_head + r->echo_count++) % RFU_ECHO_MAX], cmd, 14);
}

static const uint8_t *echo_next_row(rfu_t *r)
{
    if (r->echo_count) {
        memcpy(r->echo_row, r->echo[r->echo_head], 14);
        r->echo_head = (uint8_t)((r->echo_head + 1) % RFU_ECHO_MAX);
        --r->echo_count;
    }
    return r->echo_row;
}

enum { EV_NONE, EV_CONNECT, EV_DISCONNECT, EV_UNI, EV_OTHER };

static int rfu_receive(gift_host_t *h, const uint8_t *inner, size_t length)
{
    rfu_t *r = &h->rfu;
    if (length < 4 || inner[0] != GBA_MARKER) return EV_NONE;
    const uint16_t size = gl16(inner + 2);
    if (length < 4u + size) return EV_NONE;
    const uint8_t type = inner[1];
    const uint8_t *body = inner + 4;

    if (type == TYPE_C) {
        if (size < 2) return EV_NONE;
        if (!r->have_connect) {
            r->have_connect = true;
            memcpy(r->connect_id, body, 2);
            r->state = RFU_CHILD_NI;
            memset(&r->child_ni, 0, sizeof(r->child_ni));
            r->child_ni.payload_size = 12;
            uint8_t frame[16], accept[6] = {0};
            memcpy(accept, h->image->rfu_session_id, 2);
            memcpy(accept + 2, body, 2);
            rfu_push(r, frame, gba_frame(frame, TYPE_A, accept, 6));
            const uint8_t zero[4] = {0};
            rfu_push(r, frame, gba_frame(frame, TYPE_G, zero, 4));
            return EV_CONNECT;
        }
        return EV_OTHER;
    }
    if (type == TYPE_D) {
        r->state = RFU_DISCONNECTED;
        r->pending_count = 0;
        return EV_DISCONNECT;
    }
    if (type == TYPE_K) return EV_OTHER;
    if (type != TYPE_T || !r->have_connect || r->state == RFU_DISCONNECTED) return EV_NONE;

    /* parse_out */
    if (size < 8) return EV_NONE;
    const uint8_t slot_len = body[5];
    const uint8_t *slot = body + 8;
    const size_t have = size > 8 ? (size_t)size - 8 : 0;
    const uint8_t sl = (uint8_t)(slot_len < have ? slot_len : have);
    if (slot_len < 2 || sl < 2) return EV_NONE;
    const uint16_t f = gl16(slot);
    const uint8_t state = (f >> 10) & 0xF, ack = (f >> 9) & 1, n = (f >> 7) & 3, phase = (f >> 5) & 3,
                  ni_size = f & 0x1F;

    if (ack == 1) {
        if (r->state == RFU_PARENT_NI && r->parent_waiting && r->waiting[0] == state &&
            r->waiting[1] == n && r->waiting[2] == phase)
            r->parent_waiting = false;
        return EV_OTHER;
    }
    if (state != LCOM_UNI) {
        if (r->state != RFU_CHILD_NI && r->state != RFU_PARENT_NI) return EV_OTHER;
        uint8_t key[17] = {state, n, phase};
        const uint8_t tail = (uint8_t)(sl - 2 > 14 ? 14 : sl - 2);
        memcpy(key + 3, slot + 2, tail);
        for (uint8_t i = 0; i < r->seen_count; ++i) {
            if (r->seen_length[i] == 3 + tail && !memcmp(r->seen[i], key, 3u + tail)) {
                if (state == LCOM_NI_START || state == LCOM_NI || state == LCOM_NI_END) {
                    uint8_t s[3];
                    parent_llsf(s, state, n, phase, 1, 0);
                    push_parent_t(r, s, 3);
                }
                return EV_OTHER;
            }
        }
        if (r->seen_count < RFU_SEEN_MAX) {
            memcpy(r->seen[r->seen_count], key, 3u + tail);
            r->seen_length[r->seen_count++] = (uint8_t)(3 + tail);
        }
        const uint8_t payload_n = (uint8_t)(ni_size < sl - 2 ? ni_size : sl - 2);
        if (ni_on_child(&r->child_ni, state, ack, n, phase, slot + 2, payload_n)) {
            uint8_t s[3];
            parent_llsf(s, state, n, phase, 1, 0);
            push_parent_t(r, s, 3);
        }
        if (state == LCOM_NULL && r->child_ni.complete && r->state == RFU_CHILD_NI) {
            uint8_t frame[16];
            const uint8_t one[4] = {1, 0, 0, 0};
            rfu_push(r, frame, gba_frame(frame, TYPE_G, one, 4));
            parent_ni_sequence(r);
            r->state = RFU_PARENT_NI;
        }
        return EV_OTHER;
    }
    if (r->state != RFU_UNI) return EV_OTHER;
    memset(r->child_cmd, 0, 14);
    memcpy(r->child_cmd, slot + 2, sl - 2 < 14 ? (size_t)(sl - 2) : 14);
    r->child_cmd[0] &= 0x1F;
    echo_append(r, r->child_cmd);
    return EV_UNI;
}

/* One parent frame for this VBlank, or 0 bytes. */
static uint8_t rfu_tick(rfu_t *r, const uint16_t *words, uint8_t *frame)
{
    if (r->pending_count) {
        const uint8_t i = r->pending_head;
        r->pending_head = (uint8_t)((r->pending_head + 1) % RFU_PENDING_MAX);
        --r->pending_count;
        memcpy(frame, r->pending[i], r->pending_length[i]);
        return r->pending_length[i];
    }
    if (r->state == RFU_PARENT_NI) {
        if (r->parent_waiting) return wrap_parent_t(r, r->current_slot, r->current_length, frame);
        if (r->parent_ni_next < r->parent_ni_count) {
            const ni_item_t *it = &r->parent_ni[r->parent_ni_next++];
            uint8_t slot[16];
            parent_llsf(slot, it->state, it->n, it->phase, 0, it->size);
            memcpy(slot + 3, it->payload, it->size);
            const uint8_t length = (uint8_t)(3 + it->size);
            if (it->state == LCOM_NULL) {
                r->state = RFU_UNI;
            } else {
                r->parent_waiting = true;
                r->waiting[0] = it->state;
                r->waiting[1] = it->n;
                r->waiting[2] = it->phase;
                memcpy(r->current_slot, slot, length);
                r->current_length = length;
            }
            return wrap_parent_t(r, slot, length, frame);
        }
    }
    if (r->state == RFU_UNI) {
        uint8_t slot[3 + 70] = {0};
        parent_llsf(slot, LCOM_UNI, 0, 0, 0, 70);
        if (words)
            for (int i = 0; i < 7; ++i) pl16(slot + 3 + 2 * i, words[i]);
        memcpy(slot + 3 + 14, echo_next_row(r), 14);
        return wrap_parent_t(r, slot, sizeof(slot), frame);
    }
    return 0;
}

/* ---- host_session.py ---- */

void session_reset(gift_host_t *h)
{
    memset(&h->session, 0, sizeof(h->session));
    rel_reset(&h->rel);
    rfu_reset(&h->rfu, h->image);
}

static void deliver(gift_host_t *h, uint16_t seq, const uint8_t *payload, size_t length)
{
    const int event = rfu_receive(h, payload, length);
    if (event == EV_CONNECT && !h->session.have_connect_seq) {
        h->session.have_connect_seq = true;
        h->session.connect_seq = seq;
    }
    if (event == EV_UNI) mg_feed_child_slot(h, h->rfu.child_cmd);
}

void session_receive(gift_host_t *h, const uint8_t *wire, size_t length, uint32_t now_ms)
{
    if (h->session.stopped || length < 8) return;
    rel_t *r = &h->rel;
    const uint16_t ln = gb16(wire + 1);
    if (ln > length - 8) return;
    const uint8_t flags = wire[0];
    const uint16_t seq = gb16(wire + 3);
    const uint8_t *payload = wire + 8;
    if (!(flags & 1)) {
        if (ln < 4) return;
        uint8_t mask[16] = {0};
        memcpy(mask, payload + 4, ln - 4 < 16 ? (size_t)(ln - 4) : 16);
        on_ack(r, gb16(payload + 2), mask, now_ms);
        return;
    }
    if (!r->peer_opened && seq == REL_START && !(flags & 8)) return;
    if (flags & 8) r->peer_opened = true;
    note_received(r, seq);
    r->ack_owed = true;
    if (!r->ack_due_set) {
        r->ack_due_set = true;
        r->next_ack_ms = now_ms + RTO_BASE_MS;
    }
    if (seq == r->deliver_next) {
        ++r->deliver_next;
        deliver(h, seq, payload, ln);
        while (BIT(r->held, r->deliver_next)) {
            const uint16_t s = r->deliver_next++;
            CLEAR(r->held, s);
            deliver(h, s, r->held_data[SLOT(s)], r->held_length[SLOT(s)]);
        }
    } else if (seq_lt(r->deliver_next, seq) && (uint16_t)(seq - r->deliver_next) < REL_WINDOW &&
               !BIT(r->held, seq) && ln <= REL_IN_MAX) {
        SET(r->held, seq);
        memcpy(r->held_data[SLOT(seq)], payload, ln);
        r->held_length[SLOT(seq)] = (uint8_t)ln;
        r->held_flags[SLOT(seq)] = flags;
    }
}

size_t session_tick(gift_host_t *h, uint32_t now_ms, rel_emit_t *out)
{
    session_t *s = &h->session;
    rel_t *r = &h->rel;
    if (s->stopped) return 0;
    size_t n = rel_poll(r, now_ms, out);
    for (size_t i = 0; i < n; ++i) {
        if (out[i].flags != FLAGS_CTRL) continue;
        const uint16_t ack_id = gb16(out[i].data + 2);
        if (s->have_connect_seq && (uint16_t)(ack_id - (uint16_t)(s->connect_seq + 1)) < 0x8000)
            s->connect_ack_sent = true;
    }
    if (inflight(r) >= REL_WINDOW) return n;
    if (!(s->close_poll_sent && h->mg.disconnect_requested) && rel_outstanding(r) >= HOST_OUTSTANDING_MAX)
        return n;
    uint8_t frame[RFU_FRAME_MAX];
    if (s->close_poll_sent && h->mg.disconnect_requested && !s->disconnect_sent) {
        if (h->rfu.have_connect) {
            h->rfu.state = RFU_DISCONNECTED;
            h->rfu.pending_count = 0;
            out[n++] = rel_send(r, frame, gba_frame(frame, TYPE_D, h->rfu.connect_id, 2), now_ms);
        }
        s->disconnect_sent = true;
        mg_mark_disconnect_sent(h);
        return n;
    }
    uint16_t words[7];
    const bool uni = h->rfu.state == RFU_UNI;
    if (uni) mg_tick(h, words);
    if (!r->local_opened && !s->connect_ack_sent) return n;
    const uint8_t length = rfu_tick(&h->rfu, uni ? words : NULL, frame);
    if (!length) return n;
    out[n++] = r->local_opened ? rel_send(r, frame, length, now_ms) : rel_open(r, frame, length, now_ms);
    if (uni && (words[0] & 0xFF00) == READY_CLOSE_LINK) s->close_poll_sent = true;
    return n;
}
