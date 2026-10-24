/* The Mystery Gift leader: pokeldn/frlg/gift/host_mystery_gift.py (HostMysteryGiftEngine),
   pokeldn/gba/block.py (BlockSender, RecvBlock), pokeldn/frlg/gift/mg_link.py, and the server script
   pokeldn/frlg/gift/mg_server.py runs, as pokeldn/frlg/gift/portable.py compiles it. */
#include <string.h>

#include "gift_int.h"

/* MysteryGiftTiming, in field order (gift.h) */
enum { T_STANDBY_ECHO, T_CLIENT_READY_IDLE, T_BLOCK_GAP, T_PLAYER_IDS_REPEAT, T_BLOCK_REPEAT,
       T_RAM_SCRIPT_REPEAT, T_CLOSE_RETRY, T_CLOSE_GRACE };

/* rfu.py */
#define SEND_BLOCK_INIT 0x8800
#define SEND_BLOCK 0x8900
#define READY_EXIT_STANDBY 0x6600
#define READY_CLOSE_LINK 0x5F00
#define SEND_BLOCK_REQ 0xA100
#define SEND_PLAYER_IDS 0x7700
#define FRAG_BYTES 12
#define COUNT_PARTY 17
/* mystery_gift.py */
#define MG_LINKID_RAM_SCRIPT 25
#define MG_LINK_MAX_CHUNK 252
#define GAME_DATA_SIZE 0x64
/* mg_server.py */
enum { SVR_MSG_CARD_SENT = 2, SVR_MSG_NEWS_SENT = 3, SVR_MSG_STAMP_SENT = 4, SVR_MSG_GIFT_SENT_1 = 13 };
/* pokeldn/frlg/gift/portable.py */
enum { OP_RETURN, OP_SEND, OP_RECV, OP_GOTO, OP_GOTO_IF_EQ, OP_COPY_GAME_DATA, OP_CHECK_GAME_DATA,
       OP_CHECK_EXISTING_CARD, OP_READ_RESPONSE, OP_LOAD, OP_CHECK_QUESTIONNAIRE, OP_CHECK_RALLY_CARD,
       OP_CHECK_EXISTING_STAMPS };
enum { HAS_NO_CARD = 0, HAS_SAME_CARD = 1, HAS_DIFF_CARD = 2 };
enum { STAMPS_FULL = 1, STAMP_NEW = 2, STAMP_ALREADY_PRESENT = 3 };

static uint16_t timing(const gift_host_t *h, int field) { return h->image->timing[field]; }

/* CalcCRC16WithTable [decomp:src/util.c:250] */
static uint16_t crc16(const uint8_t *data, size_t length)
{
    uint16_t crc = 0x1121;
    for (size_t i = 0; i < length; ++i) {
        crc ^= data[i];
        for (int bit = 0; bit < 8; ++bit) crc = (crc & 1) ? (uint16_t)((crc >> 1) ^ 0x8408) : (uint16_t)(crc >> 1);
    }
    return (uint16_t)~crc;
}

static void fail(gift_host_t *h, int why)
{
    if (h->mg.failed) return;
    h->mg.failed = true;
    if (h->platform->event) h->platform->event(h->platform->context, GIFT_EVENT_REFUSED, why);
}

/* ---- words and blocks ---- */

static void queue_words(gift_host_t *h, uint16_t w0, uint16_t w1, uint16_t w2)
{
    mg_t *m = &h->mg;
    if (m->words_count == MG_WORDS_MAX) return;
    uint16_t *w = m->words[(m->words_head + m->words_count++) % MG_WORDS_MAX];
    memset(w, 0, 14);
    w[0] = w0;
    w[1] = w1;
    w[2] = w2;
}

static void queue_block(gift_host_t *h, const uint8_t *data, uint16_t length, bool ram_script)
{
    mg_t *m = &h->mg;
    if (m->blocks_count == MG_BLOCKS_MAX) return;
    m->blocks[(m->blocks_head + m->blocks_count++) % MG_BLOCKS_MAX] = (mg_block_t){data, length, ram_script};
}

static void queue_player_ids(gift_host_t *h)
{
    /* SEND_PLAYER_IDS: two players, linkPlayerIdx [1, 0, 0, 0] */
    for (int i = 0; i < timing(h, T_PLAYER_IDS_REPEAT); ++i) queue_words(h, SEND_PLAYER_IDS, 2, 1);
}

static void queue_close_words(gift_host_t *h)
{
    for (int i = 0; i < timing(h, T_STANDBY_ECHO); ++i) queue_words(h, READY_CLOSE_LINK, h->mg.exit_count, 0);
}

/* BlockSender with no ack: the watchdogs alone [block.py] */
static void sender_start(gift_host_t *h, const mg_block_t *b)
{
    mg_sender_t *s = &h->mg.sender;
    memset(s, 0, sizeof(*s));
    s->active = true;
    s->data = b->data;
    s->length = b->length;
    s->count = (uint8_t)(b->length ? (b->length + FRAG_BYTES - 1) / FRAG_BYTES : 1);
    s->state = BS_INIT;
    uint16_t repeat = timing(h, T_BLOCK_REPEAT);
    if (b->ram_script && timing(h, T_RAM_SCRIPT_REPEAT) > repeat) repeat = timing(h, T_RAM_SCRIPT_REPEAT);
    s->repeat = (uint8_t)(repeat ? repeat : 1);
}

static void block_words(const mg_sender_t *s, uint8_t index, uint16_t w[7])
{
    uint8_t chunk[FRAG_BYTES] = {0};
    const size_t at = (size_t)index * FRAG_BYTES;
    if (at < s->length) memcpy(chunk, s->data + at, s->length - at < FRAG_BYTES ? s->length - at : FRAG_BYTES);
    w[0] = (uint16_t)(SEND_BLOCK | (index & 0x1F));
    for (int i = 0; i < 6; ++i) w[1 + i] = gl16(chunk + 2 * i);
}

static void sender_tick(gift_host_t *h, uint16_t w[7])
{
    mg_sender_t *s = &h->mg.sender;
    const bool trust = h->image->flags & 4;
    memset(w, 0, 14);
    if (s->state == BS_DONE) return;
    if (s->state == BS_INIT) {
        if (++s->init_sends > 4) {             /* watchdog_init */
            s->state = BS_STREAM;
            s->index = 0;
        } else {
            w[0] = SEND_BLOCK_INIT;
            w[1] = s->count;
            w[2] = 0x80;                        /* owner 0 | OWNER_FLAG */
            return;
        }
    }
    if (s->state == BS_STREAM) {
        const uint8_t index = s->index;
        block_words(s, index, w);
        if (++s->frag_sends < s->repeat) return;
        s->frag_sends = 0;
        if (index >= s->count - 1) {
            s->state = trust ? BS_DONE : BS_HOLD;
            s->hold_sends = 0;
        } else {
            ++s->index;
        }
        return;
    }
    if (s->state == BS_HOLD) {
        if (s->hold_gap < 6 && s->hold_sends) {   /* HOLD_RESEND_GAP */
            ++s->hold_gap;
            return;
        }
        s->hold_gap = 0;
        if (++s->hold_sends > 6) {                /* watchdog_hold */
            s->state = BS_DONE;
            return;
        }
        block_words(s, (uint8_t)(s->count - 1), w);
    }
}

/* ---- MysteryGiftLinkReceiver ---- */

static void link_expect(mg_link_rx_t *rx, uint8_t ident)
{
    rx->expected = ident;
    rx->size = rx->crc = rx->length = 0;
    rx->in_header = true;
}

/* 1: a whole message, 0: more to come, -1: an error the console's MGL_Receive would raise */
static int link_feed(mg_link_rx_t *rx, const uint8_t *block, uint16_t length)
{
    if (rx->in_header) {
        if (length < 6) return -1;
        const uint16_t ident = gl16(block), crc = gl16(block + 2), size = gl16(block + 4);
        if (size > MG_BUFFER) return -1;
        if (rx->expected >= 0 && ident != (uint16_t)rx->expected) return -1;
        if (size == 0) return -1;
        rx->ident = (uint8_t)ident;
        rx->crc = crc;
        rx->size = size;
        rx->in_header = false;
        return 0;
    }
    const uint16_t remaining = (uint16_t)(rx->size - rx->length);
    const uint16_t take = remaining < MG_LINK_MAX_CHUNK ? remaining : MG_LINK_MAX_CHUNK;
    if (length < take) return -1;
    memcpy(rx->buf + rx->length, block, take);
    rx->length = (uint16_t)(rx->length + take);
    if (rx->length < rx->size) return 0;
    if (crc16(rx->buf, rx->size) != rx->crc) return -1;
    rx->expected = -1;
    return 1;
}

/* ---- the server program ---- */

static const char *version_of(const uint8_t *gd, int *code)
{
    const uint8_t *game = gd + 0x5C;
    if (!memcmp(game, "AXV", 3)) { *code = 4; return "ruby"; }
    if (!memcmp(game, "AXP", 3)) { *code = 5; return "sapphire"; }
    if (!memcmp(game, "BPE", 3)) { *code = 3; return "emerald"; }
    switch (gl32(gd + 0x10) & 0x0F) {
    case 1: *code = 1; return "firered";
    case 2: *code = 2; return "leafgreen";
    default: *code = 0xFF; return "other";
    }
}

static bool copy_game_data(gift_host_t *h)
{
    mg_server_t *s = &h->mg.server;
    if (s->received_length < GAME_DATA_SIZE) return false;
    memcpy(s->game_data, s->received, GAME_DATA_SIZE);
    s->game_data_length = GAME_DATA_SIZE;
    int version;
    version_of(s->game_data, &version);
    const gift_image_t *im = h->image;
    if (im->expect_console && im->expect_console != version) return false;
    const bool family_ok = im->game_family == 0 ? (version == 1 || version == 2) : version == 3;
    if (!family_ok) return false;
    const uint8_t *code = s->game_data + 0x5C;
    for (uint8_t i = 0; i < im->build_count; ++i) {
        const gift_build_t *b = &im->build[i];
        if (!memcmp(b->code, "\0\0\0\0", 4) || !memcmp(b->code, code, 4)) {
            s->build = b;
            return true;
        }
    }
    return false;
}

static bool validate_game_data(const uint8_t *gd, bool news)
{
    /* MysteryGift_ValidateLinkGameData [decomp:src/mystery_gift.c:373] */
    if (gl32(gd) != 0x101) return false;
    if (!(gl16(gd + 4) & 1)) return false;
    if (!(gl32(gd + 8) & 1)) return false;
    const uint32_t version = gl32(gd + 0x10);
    if (!memcmp(gd + 0x5C, "BPE", 3)) return news || ((gl16(gd + 0x0C) & (1 << 2)) && (version & ((1 << 9) | 0x180)));
    if (!(gl16(gd + 0x0C) & 1)) return false;
    return (version & 0x0F) != 0;
}

static void server_run(gift_host_t *h)
{
    mg_server_t *s = &h->mg.server;
    const gift_image_t *im = h->image;
    while (s->action == SVR_NONE && !h->mg.failed) {
        static const uint8_t size[] = {2, 1, 2, 3, 7, 1, 2, 1, 1, 2, 9, 1, 1};
        if (s->pc >= im->program_length) { fail(h, 1); return; }
        const uint8_t *p = im->program + s->pc;
        const uint8_t op = p[0];
        if (op >= sizeof(size) || s->pc + size[op] > im->program_length) { fail(h, 5); return; }
        const gift_build_t *build = s->build ? s->build : &im->build[0];
        const uint8_t *gd = s->game_data;
        switch (op) {
        case OP_RETURN:
            s->result = p[1];
            s->action = SVR_DONE;
            s->pc += 2;
            break;
        case OP_SEND:
            s->pc += 1;
            if (!s->loaded) { fail(h, 2); return; }
            s->sending = s->loaded;
            s->action = SVR_SENDING;
            break;
        case OP_RECV:
            s->recv_ident = p[1];
            s->action = SVR_RECEIVING;
            s->pc += 2;
            break;
        case OP_GOTO:
            s->pc = gl16(p + 1);
            break;
        case OP_GOTO_IF_EQ:
            s->pc = s->param == gl32(p + 1) ? gl16(p + 5) : (uint16_t)(s->pc + 7);
            break;
        case OP_COPY_GAME_DATA:
            s->pc += 1;
            if (!copy_game_data(h)) { fail(h, 3); return; }
            break;
        case OP_CHECK_GAME_DATA:
            s->param = validate_game_data(gd, p[1] != 0);
            s->pc += 2;
            break;
        case OP_CHECK_EXISTING_CARD: {
            const uint16_t flag = gl16(gd + 0x14);
            s->param = flag == 0 ? HAS_NO_CARD : flag == build->card_flag_id ? HAS_SAME_CARD : HAS_DIFF_CARD;
            s->pc += 1;
            break;
        }
        case OP_READ_RESPONSE: {
            uint8_t word[4] = {0};
            memcpy(word, s->received, s->received_length < 4 ? s->received_length : 4);
            s->param = gl32(word);
            s->pc += 1;
            break;
        }
        case OP_LOAD:
            if (p[1] >= build->slots || build->slot[p[1]] >= im->payload_count) { fail(h, 4); return; }
            s->loaded = &im->payload[build->slot[p[1]]];
            s->pc += 2;
            break;
        case OP_CHECK_QUESTIONNAIRE:
            s->param = !memcmp(gd + 0x16, p + 1, 8);
            s->pc += 9;
            break;
        case OP_CHECK_RALLY_CARD: {
            const uint16_t flag = gl16(gd + 0x14);
            if (!flag) s->param = HAS_NO_CARD;
            else if (flag == build->card_flag_id && gd[0x44] == build->card_max_stamps &&
                     gl16(gd + 0x26) == build->card_icon)
                s->param = HAS_SAME_CARD;
            else s->param = HAS_DIFF_CARD;
            s->pc += 1;
            break;
        }
        case OP_CHECK_EXISTING_STAMPS: {
            const uint8_t slots = gd[0x44] < 7 ? gd[0x44] : 7;
            bool present = false, room = false;
            for (uint8_t i = 0; i < slots; ++i) {
                const uint16_t species = gl16(gd + 0x28 + 2 * i), id = gl16(gd + 0x36 + 2 * i);
                present |= species == build->stamp_species || id == build->stamp_id;
                room |= species == 0 && id == 0;
            }
            s->param = present ? STAMP_ALREADY_PRESENT : !room ? STAMPS_FULL : STAMP_NEW;
            s->pc += 1;
            break;
        }
        default:
            fail(h, 5);
            return;
        }
    }
}

/* ---- HostMysteryGiftEngine ---- */

static void set_state(gift_host_t *h, uint8_t state) { h->mg.state = state; }

static void begin_close(gift_host_t *h)
{
    set_state(h, MG_CLOSE);
    queue_close_words(h);
    h->mg.close_retry_wait = timing(h, T_CLOSE_RETRY);
}

static void queue_message(gift_host_t *h, const gift_payload_t *payload)
{
    mg_t *m = &h->mg;
    const uint16_t size = payload->size ? payload->size : MG_BUFFER;
    uint8_t *buf = m->message + 6;
    memset(buf, 0, size);
    memcpy(buf, payload->data, payload->length < size ? payload->length : size);
    pl16(m->message, payload->ident);
    pl16(m->message + 2, crc16(buf, size));
    pl16(m->message + 4, size);
    const bool ram = payload->ident == MG_LINKID_RAM_SCRIPT;
    queue_block(h, m->message, 6, ram);
    for (uint16_t at = 0; at < size; at = (uint16_t)(at + MG_LINK_MAX_CHUNK))
        queue_block(h, buf + at, (uint16_t)(size - at < MG_LINK_MAX_CHUNK ? size - at : MG_LINK_MAX_CHUNK), ram);
}

static bool drain_recv_blocks(gift_host_t *h)
{
    mg_t *m = &h->mg;
    while (m->recv_count && m->link_rx.expected >= 0) {
        const uint8_t i = m->recv_head;
        m->recv_head = (uint8_t)((m->recv_head + 1) % MG_RECV_BLOCKS_MAX);
        --m->recv_count;
        const int r = link_feed(&m->link_rx, m->recv_blocks[i], m->recv_block_length[i]);
        if (r < 0) {
            /* A retransmit of the console's previous message: expect the same ident again. */
            link_expect(&m->link_rx, (uint8_t)m->link_rx.expected);
            continue;
        }
        if (r == 0) continue;
        mg_server_t *s = &m->server;
        if (s->action != SVR_RECEIVING || m->link_rx.ident != s->recv_ident) { fail(h, 6); return false; }
        memcpy(s->received, m->link_rx.buf, m->link_rx.size);
        s->received_length = m->link_rx.size;
        s->action = SVR_NONE;
        return true;
    }
    return false;
}

static void finish_gift(gift_host_t *h)
{
    const uint8_t r = h->mg.server.result;
    h->mg.gift_sent = r == SVR_MSG_CARD_SENT || r == SVR_MSG_STAMP_SENT || r == SVR_MSG_GIFT_SENT_1 ||
                      r == SVR_MSG_NEWS_SENT;
    if (h->platform->event) h->platform->event(h->platform->context, GIFT_EVENT_RESULT, r);
    begin_close(h);
}

static void pump_server(gift_host_t *h)
{
    mg_t *m = &h->mg;
    while (m->state == MG_GIFT && !m->failed) {
        server_run(h);
        if (m->failed) return;
        mg_server_t *s = &m->server;
        if (s->action == SVR_SENDING) {
            if (m->blocks_count || m->sender.active) return;
            queue_message(h, s->sending);
            return;
        }
        if (s->action == SVR_RECEIVING) {
            if (m->link_rx.expected < 0) link_expect(&m->link_rx, s->recv_ident);
            if (!drain_recv_blocks(h)) return;
            continue;
        }
        if (s->action == SVR_DONE) {
            finish_gift(h);
            return;
        }
    }
}

static void begin_gift(gift_host_t *h)
{
    set_state(h, MG_GIFT);
    pump_server(h);
}

void mg_reset(gift_host_t *h)
{
    mg_t *m = &h->mg;
    memset(m, 0, sizeof(*m));
    m->state = MG_LINK_PLAYER;
    m->child_mp_id = -1;
    m->close_grace_wait = m->close_retry_wait = -1;
    m->link_rx.expected = -1;
    queue_player_ids(h);
    m->expect_link_player = true;
    queue_words(h, SEND_BLOCK_REQ, 0, 0);
}

static void complete_link_player_barrier(gift_host_t *h)
{
    mg_t *m = &h->mg;
    if (m->state != MG_LINK_PLAYER) return;
    m->pending_standby = false;
    set_state(h, MG_START);
    m->standby_seen = true;
    m->idle_run = 0;
}

static void on_child_block(gift_host_t *h, uint8_t count, const uint8_t *data, uint16_t length)
{
    mg_t *m = &h->mg;
    if (m->state == MG_LINK_PLAYER && m->expect_link_player) {
        m->expect_link_player = false;
        /* parse_block: both "GameFreak inc." magics [linkplayer.py] */
        if (count != COUNT_PARTY || length < 60 || memcmp(data, "GameFreak inc.", 14) ||
            memcmp(data + 44, "GameFreak inc.", 14)) {
            memset(&m->rx, 0, sizeof(m->rx));
            return;
        }
        m->link_player_seen = true;
        m->linked = true;
        m->host_link_player_queued = true;
        queue_block(h, h->image->link_player, 200, false);
        if (h->platform->event) h->platform->event(h->platform->context, GIFT_EVENT_LINKED, 0);
        return;
    }
    if (m->state == MG_GIFT) {
        if (m->recv_count == MG_RECV_BLOCKS_MAX) return;
        const uint8_t i = (uint8_t)((m->recv_head + m->recv_count++) % MG_RECV_BLOCKS_MAX);
        memcpy(m->recv_blocks[i], data, length);
        m->recv_block_length[i] = length;
        if (drain_recv_blocks(h)) pump_server(h);
    }
}

static void on_child_standby(gift_host_t *h, uint16_t count)
{
    mg_t *m = &h->mg;
    for (int i = 0; i < timing(h, T_STANDBY_ECHO); ++i) queue_words(h, READY_EXIT_STANDBY, count, 0);
    if (count + 1 > m->exit_count) m->exit_count = (uint16_t)(count + 1);
    if (m->state == MG_LINK_PLAYER && m->link_player_seen) {
        if (m->host_link_player_complete) {
            complete_link_player_barrier(h);
        } else {
            m->pending_standby = true;
            m->pending_standby_count = count;
        }
    }
}

static void on_child_close(gift_host_t *h, uint16_t count)
{
    mg_t *m = &h->mg;
    if (count > m->exit_count) m->exit_count = count;
    if (m->state == MG_LINK_PLAYER || m->state == MG_START || m->state == MG_GIFT) begin_close(h);
    if (m->state != MG_CLOSE) return;
    if (!m->close_confirmed) {
        m->close_confirmed = true;
        m->close_grace_wait = timing(h, T_CLOSE_GRACE);
    }
}

void mg_feed_child_slot(gift_host_t *h, const uint8_t slot[14])
{
    mg_t *m = &h->mg;
    static const uint8_t idle[14] = {0};
    if (!memcmp(slot, idle, 14)) {
        ++m->idle_run;
        if (m->state == MG_START && m->standby_seen && m->idle_run >= timing(h, T_CLIENT_READY_IDLE))
            begin_gift(h);
        return;
    }
    m->idle_run = 0;
    const uint16_t w0 = gl16(slot), op = w0 & 0xFF00;
    if (op == SEND_BLOCK_INIT) {
        /* owner byte = mpId | 0x80; mpId 0: the console has not taken SEND_PLAYER_IDS */
        const int16_t mp = slot[4] & 0x7F;
        if (mp != m->child_mp_id) m->child_mp_id = mp;
        if (m->state == MG_LINK_PLAYER && mp != 1) queue_player_ids(h);
        const uint8_t count = (uint8_t)gl16(slot + 2);
        mg_rx_t *rx = &m->rx;
        if (!rx->receiving || rx->done || count != rx->count) {
            memset(rx, 0, sizeof(*rx));
            rx->count = count <= 32 ? count : 0;
            rx->receiving = true;
        }
    } else if (op == SEND_BLOCK) {
        mg_rx_t *rx = &m->rx;
        const uint8_t index = w0 & 0x1F;
        const bool was_done = rx->done;
        if (rx->receiving && index < rx->count) {
            rx->flags |= 1u << index;
            memcpy(rx->buf + index * FRAG_BYTES, slot + 2, FRAG_BYTES);
            if (rx->flags == (rx->count == 32 ? 0xFFFFFFFFu : (1u << rx->count) - 1)) rx->done = true;
        }
        if (rx->done && !was_done) {
            const uint8_t count = rx->count;
            rx->receiving = rx->done = false;
            rx->flags = 0;
            on_child_block(h, count, rx->buf, (uint16_t)(count * FRAG_BYTES));
        }
    } else if (op == READY_EXIT_STANDBY) {
        on_child_standby(h, gl16(slot + 2));
    } else if (op == READY_CLOSE_LINK) {
        on_child_close(h, gl16(slot + 2));
    }
}

static void tick_close(gift_host_t *h)
{
    mg_t *m = &h->mg;
    if (m->close_grace_wait >= 0) {
        if (--m->close_grace_wait <= 0) {
            m->close_grace_wait = -1;
            m->disconnect_requested = true;
            return;
        }
    }
    if (--m->close_retry_wait <= 0) {
        queue_close_words(h);
        m->close_retry_wait = timing(h, T_CLOSE_RETRY);
    }
}

void mg_tick(gift_host_t *h, uint16_t w[7])
{
    mg_t *m = &h->mg;
    memset(w, 0, 14);
    if (m->state == MG_CLOSE && !m->disconnect_requested) tick_close(h);
    if (m->words_count) {
        memcpy(w, m->words[m->words_head], 14);
        m->words_head = (uint8_t)((m->words_head + 1) % MG_WORDS_MAX);
        --m->words_count;
        return;
    }
    if (m->gap > 0) {
        --m->gap;
        return;
    }
    if (!m->sender.active && m->blocks_count) {
        const mg_block_t b = m->blocks[m->blocks_head];
        m->blocks_head = (uint8_t)((m->blocks_head + 1) % MG_BLOCKS_MAX);
        --m->blocks_count;
        sender_start(h, &b);
    }
    if (m->sender.active) {
        sender_tick(h, w);
        if (m->sender.state == BS_DONE) {
            if (m->state == MG_LINK_PLAYER) {
                m->host_link_player_complete = true;
                if (m->pending_standby) complete_link_player_barrier(h);
            }
            m->sender.active = false;
            m->gap = timing(h, T_BLOCK_GAP);
            if (!m->blocks_count && m->state == MG_GIFT) {
                mg_server_t *s = &m->server;
                if (s->action != SVR_SENDING) { fail(h, 7); return; }
                s->action = SVR_NONE;
                s->loaded = NULL;
                pump_server(h);
            }
        }
    }
}

void mg_mark_disconnect_sent(gift_host_t *h)
{
    h->mg.done = true;
    set_state(h, MG_DONE);
}
