/* The portable gift host's state, one struct per Python object it ports. gift.h has the contract. */
#pragma once

#include "gift.h"

/* Big- and little-endian fields. */
static inline uint16_t gb16(const uint8_t *p) { return (uint16_t)(p[0] << 8 | p[1]); }
static inline uint32_t gb32(const uint8_t *p)
{
    return (uint32_t)p[0] << 24 | (uint32_t)p[1] << 16 | (uint32_t)p[2] << 8 | p[3];
}
static inline uint16_t gl16(const uint8_t *p) { return (uint16_t)(p[0] | p[1] << 8); }
static inline uint32_t gl32(const uint8_t *p)
{
    return (uint32_t)p[0] | (uint32_t)p[1] << 8 | (uint32_t)p[2] << 16 | (uint32_t)p[3] << 24;
}
static inline void pb16(uint8_t *p, uint16_t v) { p[0] = (uint8_t)(v >> 8); p[1] = (uint8_t)v; }
static inline void pb32(uint8_t *p, uint32_t v)
{
    p[0] = (uint8_t)(v >> 24); p[1] = (uint8_t)(v >> 16); p[2] = (uint8_t)(v >> 8); p[3] = (uint8_t)v;
}
static inline void pl16(uint8_t *p, uint16_t v) { p[0] = (uint8_t)v; p[1] = (uint8_t)(v >> 8); }
static inline void pl32(uint8_t *p, uint32_t v)
{
    p[0] = (uint8_t)v; p[1] = (uint8_t)(v >> 8); p[2] = (uint8_t)(v >> 16); p[3] = (uint8_t)(v >> 24);
}

/* ---- pokeldn/ldn/reliable.py: HostReliableSession over ReliableLink ---- */

#define REL_WINDOW 128          /* MAX_INFLIGHT: the selective-ack mask spans 128 ids */
#define REL_START 0xFFF0
#define REL_OUT_MAX 96          /* a parent 'T' carrying the 70-byte table is 88 bytes */
#define REL_IN_MAX 96           /* the console's frames: 'T' 28, 'K' 16, its metadata 46 */
#define REL_RTT_WINDOW 7
#define REL_EMIT_MAX 24

typedef struct {
    uint8_t data[REL_OUT_MAX];
    uint8_t length, flags, resends;
    bool acked;
    uint32_t last_tx_ms;
} rel_out_t;

typedef struct {
    uint16_t seq, ack;
    uint8_t flags;
    bool retransmitted;
    const uint8_t *data;        /* into the send ring, or the ack built in rel_t.ack_frame */
    uint8_t length;
} rel_emit_t;

typedef struct {
    uint16_t out_seq, window_lo, recv_next, deliver_next;
    rel_out_t out[REL_WINDOW];
    uint8_t ooo[REL_WINDOW / 8];            /* recv_ooo: ids received ahead of recv_next */
    uint8_t held[REL_WINDOW / 8];           /* _deliver_buf: frames waiting for delivery */
    uint8_t held_data[REL_WINDOW][REL_IN_MAX];
    uint8_t held_length[REL_WINDOW], held_flags[REL_WINDOW];
    float rtt[REL_RTT_WINDOW];
    uint8_t rtt_count;
    int32_t peer_gap;                        /* -1: none */
    uint8_t gap_nacks;
    bool local_opened, peer_opened, ack_owed;
    bool ack_due_set;
    uint32_t next_ack_ms;
    uint8_t ack_frame[20];
} rel_t;

/* ---- pokeldn/gba/ni.py, rfu.py, rfu_leader.py: the RFU leader ---- */

#define RFU_PENDING_MAX 16
#define RFU_FRAME_MAX 96
#define RFU_ECHO_MAX 64
#define RFU_SEEN_MAX 48
#define RFU_NI_SEQ_MAX 8

typedef struct {
    bool complete, have_size;
    uint8_t payload_size;
    uint16_t data_size;
    uint8_t header[16], header_length;
    uint8_t buf[64];
    uint16_t buf_length;
    uint8_t phase_count[4];
    uint8_t game_data[64];
    uint16_t game_data_length;
    bool finalized;
} ni_recv_t;

typedef struct {
    uint8_t state, n, phase, size;
    uint8_t payload[8];
} ni_item_t;

enum { RFU_WAIT_CONNECT, RFU_CHILD_NI, RFU_PARENT_NI, RFU_UNI, RFU_DISCONNECTED };

typedef struct {
    uint8_t state;
    bool have_connect;
    uint8_t connect_id[2];
    uint32_t ts;
    uint8_t child_cmd[14];
    /* ChildEcho */
    uint8_t echo[RFU_ECHO_MAX][14];
    uint8_t echo_head, echo_count;
    uint8_t echo_row[14];
    /* pending frames, oldest first */
    uint8_t pending[RFU_PENDING_MAX][RFU_FRAME_MAX];
    uint8_t pending_length[RFU_PENDING_MAX];
    uint8_t pending_head, pending_count;
    ni_recv_t child_ni;
    ni_item_t parent_ni[RFU_NI_SEQ_MAX];
    uint8_t parent_ni_count, parent_ni_next;
    bool parent_waiting;
    uint8_t waiting[3];                     /* state, n, phase */
    uint8_t current_slot[16], current_length;
    uint8_t seen[RFU_SEEN_MAX][17];         /* state, n, phase, then the slot past its LLSF */
    uint8_t seen_length[RFU_SEEN_MAX];
    uint8_t seen_count;
} rfu_t;

/* ---- pokeldn/gba/block.py, pokeldn/frlg/gift/host_mystery_gift.py, mg_link.py, mg_server.py ---- */

#define MG_WORDS_MAX 48
#define MG_BLOCKS_MAX 8
#define MG_RECV_BLOCKS_MAX 8
#define MG_BUFFER 1024

enum { MG_LINK_PLAYER, MG_START, MG_GIFT, MG_CLOSE, MG_DONE };
enum { BS_INIT, BS_STREAM, BS_HOLD, BS_DONE };

typedef struct {
    const uint8_t *data;
    uint16_t length;
    bool ram_script;
} mg_block_t;

typedef struct {
    bool active;
    const uint8_t *data;
    uint16_t length;
    uint8_t count, state, index, init_sends, hold_sends, hold_gap, frag_sends, repeat;
} mg_sender_t;

typedef struct {
    uint8_t count;
    uint32_t flags;
    uint8_t buf[32 * 12];
    bool receiving, done;
} mg_rx_t;

typedef struct {
    int16_t expected;                        /* -1: not active */
    uint8_t ident;
    uint16_t size, crc, length;
    bool in_header;
    uint8_t buf[MG_BUFFER];
} mg_link_rx_t;

enum { SVR_NONE, SVR_SENDING, SVR_RECEIVING, SVR_DONE };

typedef struct {
    uint16_t pc;
    uint32_t param;
    uint8_t action, recv_ident, result;
    const gift_payload_t *loaded;
    const gift_payload_t *sending;
    const gift_build_t *build;
    uint8_t game_data[128];
    uint16_t game_data_length;
    uint8_t received[MG_BUFFER];
    uint16_t received_length;
} mg_server_t;

typedef struct {
    uint8_t state;
    bool done, disconnect_requested, gift_sent, linked, failed;
    uint16_t words[MG_WORDS_MAX][7];
    uint8_t words_head, words_count;
    mg_block_t blocks[MG_BLOCKS_MAX];
    uint8_t blocks_head, blocks_count;
    mg_sender_t sender;
    uint16_t gap;
    bool expect_link_player, link_player_seen, standby_seen, host_link_player_queued;
    bool host_link_player_complete, pending_standby;
    uint16_t pending_standby_count;
    uint16_t idle_run, exit_count;
    bool close_confirmed;
    int32_t close_grace_wait, close_retry_wait;   /* -1: off */
    int16_t child_mp_id;                          /* -1: none yet */
    mg_rx_t rx;
    mg_link_rx_t link_rx;
    uint8_t recv_blocks[MG_RECV_BLOCKS_MAX][32 * 12];
    uint16_t recv_block_length[MG_RECV_BLOCKS_MAX];
    uint8_t recv_head, recv_count;
    uint8_t message[6 + MG_BUFFER];               /* the message in flight: header block, then chunks */
    mg_server_t server;
} mg_t;

/* ---- pokeldn/frlg/link/host_session.py ---- */

typedef struct {
    bool have_connect_seq, connect_ack_sent, close_poll_sent, disconnect_sent, stopped;
    uint16_t connect_seq;
} session_t;

/* ---- pokeldn/ldn/host_pia.py: HostPeerProtocol, and the join it accepted ---- */

#define PIA_CARRY_DEPTH 4

typedef struct {
    uint8_t protocols[16][2], protocol_count;
    uint8_t source_constant[8];
    uint16_t source_var, destination_var;
    uint8_t destination_constant[8];
    uint8_t token[32];
    uint8_t num_players, num_participants;
    uint8_t ip[4];
    uint16_t port;
    uint8_t players[2][16 + 4 + 1 + 40];      /* player id, name size, encoding, name */
    uint8_t player_length[2];
} pia_join_t;

typedef struct {
    uint16_t seq, ack;
    uint8_t flags;
    bool retransmitted;
} pia_carried_t;

typedef struct {
    bool joined, net_acked, property_started, session_join_seen, finalized, have_join;
    bool have_rtt_template, rtt_due_set;
    uint32_t net_sequence;
    uint64_t next_net_us, next_property_us, next_accept_us, next_rtt_us, next_tick_us;
    bool accept_due, tick_due;
    uint64_t last_rx_us, last_quiet_retransmit_us;
    bool have_rx;
    pia_join_t join;
    uint16_t guest_var;
    uint8_t guest_ip[4];
    uint16_t session_packet_id, reliable_packet_id;
    uint8_t rtt_template[21];
    uint64_t rtt_systime;
    uint64_t rtt_pending_systime[8];
    uint64_t rtt_pending_us[8];
    uint8_t rtt_pending_count;
    uint64_t nonce;
    pia_carried_t carry[PIA_CARRY_DEPTH][REL_EMIT_MAX];
    uint8_t carry_count[PIA_CARRY_DEPTH];
    uint8_t carry_lists;
} pia_t;

/* ---- vendor/LDN APNetwork: the seated station ---- */

typedef struct {
    bool associated, seated;
    uint8_t mac[6];
    uint8_t ip[4];
    uint8_t name[32];
    uint8_t platform;
} station_t;

struct gift_host {
    const gift_image_t *image;
    const gift_platform_t *platform;
    uint64_t now_us;
    uint32_t advert_version;
    bool app_active;
    station_t station;
    uint16_t ip_ident;
    bool active;                       /* a session runs: the station authenticated */
    bool ending;                       /* the station left; the next poll resets */
    uint64_t absent_since_us, seated_us;
    bool absence_logged;
    rel_t rel;
    rfu_t rfu;
    mg_t mg;
    session_t session;
    pia_t pia;
    uint8_t scratch[1600];
    uint8_t frame[1600];
};

/* gift_ldn.c */
void gift_send_udp(gift_host_t *h, const uint8_t dst_ip[4], const uint8_t *payload, size_t length);
void gift_note_app_active(gift_host_t *h);
/* gift_pia.c */
void pia_reset(gift_host_t *h);
void pia_participant_joined(gift_host_t *h);
void pia_receive(gift_host_t *h, const uint8_t *datagram, size_t length, const uint8_t src_ip[4]);
uint64_t pia_tick(gift_host_t *h);
/* gift_link.c */
void rel_reset(rel_t *r);
void rfu_reset(rfu_t *r, const gift_image_t *image);
void session_reset(gift_host_t *h);
void session_receive(gift_host_t *h, const uint8_t *payload, size_t length, uint32_t now_ms);
size_t session_tick(gift_host_t *h, uint32_t now_ms, rel_emit_t *out);
void rel_note_rtt(rel_t *r, float rtt_ms);
uint16_t rel_outstanding(const rel_t *r);
bool rel_entry_live(const rel_t *r, uint16_t seq);
const uint8_t *rel_entry_data(const rel_t *r, uint16_t seq, uint8_t *length);
/* gift_mg.c */
void mg_reset(gift_host_t *h);
void mg_feed_child_slot(gift_host_t *h, const uint8_t slot[14]);
void mg_tick(gift_host_t *h, uint16_t words[7]);
void mg_mark_disconnect_sent(gift_host_t *h);
