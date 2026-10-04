/* pokeldn radio: an ESP32 as the LDN radio of a host on USB serial. LDN has no 4-way handshake:
   the host derives the CCMP key and the board installs it. Message set: docs/hardware_esp32.md. */
#include <stdatomic.h>
#include <stdio.h>
#include <string.h>

#include "esp_app_desc.h"
#include "esp_chip_info.h"
#include "esp_event.h"
#include "esp_mac.h"
#include "esp_private/wifi.h"
#include "esp_random.h"
#include "esp_timer.h"
#include "esp_wifi.h"
#include "driver/gpio.h"
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "freertos/task.h"
#include "nvs_flash.h"

#include "display.h"
#include "led.h"
#include "private_wifi.h"
#include "usbwatch.h"
#include "wire.h"

#define PROTOCOL_VERSION 1

enum {
    CMD_HELLO = 0x01, CMD_BAUD = 0x02, CMD_CHANNEL = 0x03, CMD_STA_JOIN = 0x04, CMD_STOP = 0x05,
    CMD_AP_START = 0x06, CMD_AP_KICK = 0x07, CMD_ETH_TX = 0x08, CMD_RAW_TX = 0x09,
    CMD_SNIFF = 0x0A, CMD_STATUS = 0x0B, CMD_BENCH = 0x0C, CMD_LED = 0x0D, CMD_DISPLAY = 0x0E,
    CMD_ALIVE = 0x0F,
};
/* A host that sent CMD_ALIVE and then nothing for this long is gone: the board leaves the network,
   so the console does not keep a seat nobody answers. docs/hardware_esp32.md, The host watchdog. */
#define HOST_SILENT_US 5000000
enum {
    MSG_INFO = 0x81, MSG_RESULT = 0x82, MSG_RX_MGMT = 0x84, MSG_RX_ETH = 0x85, MSG_LINK = 0x86,
    MSG_STA_JOINED = 0x87, MSG_STA_LEFT = 0x88, MSG_STATUS = 0x89, MSG_BENCH = 0x8A,
    MSG_RX_SNIFF = 0x8C, MSG_TX_DONE = 0x8D, MSG_BUTTON = 0x8E, MSG_RX_CENSUS = 0x8F,
};
enum { AP_FLAG_STOCK_JOIN = 1, AP_FLAG_NO_QOS = 2, AP_FLAG_NO_DATA_TRACE = 4, AP_FLAG_LONG_BEACON = 0x40,
       AP_FLAG_NO_PROMISC = 0x80 };
enum { AP_FLAG2_NO_NOISE_CHECK = 1, AP_FLAG2_NOISE_250 = 2, AP_FLAG2_RX_TIME = 4, AP_FLAG2_RETRY_7_4 = 8,
       AP_FLAG2_CENSUS = 0x10 };
static uint8_t s_ap_flags2;
/* Flag bits 3..5 pin the AP's data rate: 0 leaves rate control on. docs/hardware_esp32.md */
#define AP_FLAG_RATE(flags) (((flags) >> 3) & 7)
static const wifi_phy_rate_t AP_FIXED_RATES[8] = {
    0, WIFI_PHY_RATE_1M_L, WIFI_PHY_RATE_11M_L, WIFI_PHY_RATE_6M, WIFI_PHY_RATE_12M,
    WIFI_PHY_RATE_24M, WIFI_PHY_RATE_36M, WIFI_PHY_RATE_54M,
};
enum mode { MODE_IDLE, MODE_STA_JOINING, MODE_STA, MODE_AP, MODE_SNIFF };

static const uint8_t BROADCAST[6] = {0xff, 0xff, 0xff, 0xff, 0xff, 0xff};
static const uint8_t LDN_ACTION[4] = {0x7f, 0x00, 0x22, 0xaa};

/* The RSN element a Switch station sends: CCMP, PSK, capabilities 0x000c. */
static uint8_t s_rsn_ie[] = {
    0x30, 0x14, 0x01, 0x00, 0x00, 0x0f, 0xac, 0x04, 0x01, 0x00, 0x00, 0x0f, 0xac, 0x04,
    0x01, 0x00, 0x00, 0x0f, 0xac, 0x02, 0x0c, 0x00,
};

static _Atomic enum mode s_mode = MODE_IDLE;
static uint8_t s_key[16], s_peer[6], s_sta_mac[6], s_sniff_mac[6];
static bool s_census;   /* SNIFF with MAC ff:ff:ff:ff:ff:ff: every frame, FCS failures too */
static uint8_t s_ap_flags;
static int64_t s_join_started;
static atomic_bool s_assoc_seen;
static atomic_uint s_rx_mgmt, s_rx_eth, s_tx_eth, s_tx_eth_failed, s_tx_raw, s_tx_raw_failed;
static atomic_uint s_tx_acked, s_tx_unacked;
static atomic_uint s_rx_sniff;   /* frames RX_SNIFF carried: the LED's activity while sniffing */
static atomic_int s_ap_stations;
static atomic_uint s_presses;   /* BOOT presses: each wakes the screen */
static atomic_uint s_led_alarm;   /* a join that failed or a key refused: the LED's warning */
static atomic_uint s_tx_eth_retried;   /* ETH_TX calls that found the driver's queue full */
static atomic_int s_tx_eth_last_err;
/* ETH_TX's own time in the driver: the handler maximum in STATUS covers every command type. */
static atomic_uint s_tx_eth_max_us, s_tx_eth_total_us, s_tx_eth_slow;
/* When each accepted ETH_TX entered the driver, matched in order to the driver's TX-done of a data
   frame: the time a frame waits in the Wi-Fi queue and on the air. docs/hardware_esp32.md. */
#define TX_RING 256
static uint32_t s_tx_handed[TX_RING];
static atomic_uint s_tx_handed_head, s_tx_handed_tail;
static atomic_uint s_tx_queued_max_us, s_tx_queued_total_us, s_tx_queued_n;
static QueueHandle_t s_ap_joins;   /* station MACs whose association response went out */
static int s_ap_pairwise;
static int (*s_stock_sta_connect)(uint8_t *bssid);
static bool (*s_stock_ap_join)(priv_join_param_t *join);

static void result(uint8_t command, int32_t code)
{
    uint8_t head[5] = {command};
    memcpy(head + 1, &code, 4);
    wire_send(MSG_RESULT, head, sizeof(head), NULL, 0);
}

static wifi_interface_t current_interface(void)
{
    return atomic_load(&s_mode) == MODE_AP ? WIFI_IF_AP : WIFI_IF_STA;
}

/* The PHY byte pair of RX_SNIFF and RX_CENSUS: sig_mode (0 legacy, 1 HT, 3 VHT), then mcs|cwb<<7.
   An HE chip reports cur_bb_format and the HT-SIG instead (esp_wifi_he_types.h); its rate field
   is the L-SIG rate code for an OFDM frame. docs/hardware_esp32.md, Supported boards. */
static uint8_t rx_sig_mode(const wifi_pkt_rx_ctrl_t *c)
{
#if CONFIG_SOC_WIFI_HE_SUPPORT
    return c->cur_bb_format == RX_BB_FORMAT_HT ? 1 : c->cur_bb_format == RX_BB_FORMAT_VHT ? 3 : 0;
#else
    return c->sig_mode;
#endif
}

static uint8_t rx_mcs_cwb(const wifi_pkt_rx_ctrl_t *c)
{
#if CONFIG_SOC_WIFI_HE_SUPPORT
    return c->cur_bb_format == RX_BB_FORMAT_HT ? (c->he_siga1 & 0x7f) | (c->he_siga1 & 0x80) : 0;
#else
    return c->mcs | (c->cwb << 7);
#endif
}

/* Census: u32 receive time, i8 RSSI, i8 noise floor, u8 rx_state (0 good), u8 packet type,
   u8 sig_mode, u8 rate, u8 mcs|cwb<<7, u16 sig_len, then the frame's first 16 bytes. */
static void census_send(const wifi_promiscuous_pkt_t *packet, wifi_promiscuous_pkt_type_t type)
{
    const wifi_pkt_rx_ctrl_t *c = &packet->rx_ctrl;
    const uint32_t stamp = c->timestamp;
    const uint16_t sig_len = c->sig_len;
    uint8_t head[13];
    memcpy(head, &stamp, 4);
    head[4] = (uint8_t)c->rssi; head[5] = (uint8_t)c->noise_floor; head[6] = c->rx_state;
    head[7] = (uint8_t)type; head[8] = rx_sig_mode(c); head[9] = c->rate;
    head[10] = rx_mcs_cwb(c);
    memcpy(head + 11, &sig_len, 2);
    atomic_fetch_add(&s_rx_sniff, 1);
    wire_send(MSG_RX_CENSUS, head, sizeof(head), packet->payload, sig_len < 16 ? sig_len : 16);
}

static void promiscuous_rx(void *buffer, wifi_promiscuous_pkt_type_t type)
{
    const wifi_promiscuous_pkt_t *packet = buffer;
    if (atomic_load(&s_mode) == MODE_SNIFF && s_census) {
        census_send(packet, type);
        return;
    }
    if (atomic_load(&s_mode) == MODE_AP && (s_ap_flags2 & AP_FLAG2_CENSUS) &&
        (packet->rx_ctrl.rx_state || type != WIFI_PKT_DATA || packet->rx_ctrl.sig_len < 28 ||
         memcmp(packet->payload + 4, s_peer, 6))) {
        /* The access point's census: everything but its stations' good data frames to it. */
        census_send(packet, type);
        if (packet->rx_ctrl.rx_state || type == WIFI_PKT_CTRL || type == WIFI_PKT_MISC) return;
    }
    if (atomic_load(&s_mode) == MODE_SNIFF) {
        /* Sniff: every management or data frame to or from one MAC, whole, without FCS. */
        const int length = (int)packet->rx_ctrl.sig_len - 4;
        const uint8_t *frame = packet->payload;
        if ((type == WIFI_PKT_DATA || type == WIFI_PKT_MGMT) && length >= 24 && length <= 1600 &&
            (!memcmp(frame + 4, s_sniff_mac, 6) || !memcmp(frame + 10, s_sniff_mac, 6))) {
            /* The PHY fields: a flood's airtime is its bytes over its rate. */
            const uint8_t head[5] = {packet->rx_ctrl.channel, (uint8_t)packet->rx_ctrl.rssi,
                                     rx_sig_mode(&packet->rx_ctrl), packet->rx_ctrl.rate,
                                     rx_mcs_cwb(&packet->rx_ctrl)};
            atomic_fetch_add(&s_rx_sniff, 1);
            wire_send(MSG_RX_SNIFF, head, sizeof(head), frame, length);
        } else if (type == WIFI_PKT_CTRL && length == 10 && frame[0] == 0xD4) {
            /* Every ACK on the channel: it names only its receiver. Whether a data frame was
               acknowledged is read off the one that follows it. docs/hardware_esp32.md */
            const uint8_t head[5] = {packet->rx_ctrl.channel, (uint8_t)packet->rx_ctrl.rssi,
                                     rx_sig_mode(&packet->rx_ctrl), packet->rx_ctrl.rate,
                                     rx_mcs_cwb(&packet->rx_ctrl)};
            atomic_fetch_add(&s_rx_sniff, 1);
            wire_send(MSG_RX_SNIFF, head, sizeof(head), frame, length);
        }
        return;
    }
    if (type == WIFI_PKT_DATA) {
        const int length = (int)packet->rx_ctrl.sig_len - 4;
        const uint8_t *frame = packet->payload;
        if (atomic_load(&s_mode) != MODE_AP || length < 24) return;
        const uint8_t head[2] = {packet->rx_ctrl.channel, (uint8_t)packet->rx_ctrl.rssi};
        if (!memcmp(frame + 4, s_peer, 6)) {
            /* A station's frame to our BSSID: its first 40 bytes (802.11 and CCMP headers), for
               the trace; the driver delivers the frame itself through RX_ETH. */
            if (s_ap_flags2 & AP_FLAG2_RX_TIME) {
                /* RX_TIME: the head grows by the MAC's u32 receive time in us. */
                uint8_t stamped[6] = {head[0], head[1]};
                const uint32_t stamp = packet->rx_ctrl.timestamp;   /* a bit-field */
                memcpy(stamped + 2, &stamp, 4);
                wire_send(MSG_RX_MGMT, stamped, 6, frame, length < 40 ? length : 40);
            } else if (!(s_ap_flags & AP_FLAG_NO_DATA_TRACE))
                wire_send(MSG_RX_MGMT, head, 2, frame, length < 40 ? length : 40);
        } else if ((frame[1] & 3) == 0 && !memcmp(frame + 16, s_peer, 6) &&
                   memcmp(frame + 10, s_peer, 6) && length <= 1600) {
            /* A station's broadcast sent straight to the BSS (no DS bits, group key): an AP drops
               it, so it goes to the host whole, still encrypted. docs/hardware_esp32.md */
            wire_send(MSG_RX_MGMT, head, 2, frame, length);
        }
        return;
    }
    if (type != WIFI_PKT_MGMT) return;
    const uint8_t *frame = packet->payload;
    const int length = (int)packet->rx_ctrl.sig_len - 4;   /* sig_len counts the FCS */
    if (length < 24) return;
    const uint8_t subtype = frame[0] & 0xfc;
    if (subtype == 0xd0 && length >= 24 + 4 && !memcmp(frame + 24, LDN_ACTION, 4)) {
        const uint8_t head[2] = {packet->rx_ctrl.channel, (uint8_t)packet->rx_ctrl.rssi};
        atomic_fetch_add(&s_rx_mgmt, 1);
        wire_send(MSG_RX_MGMT, head, 2, frame, length);
    } else if (atomic_load(&s_mode) == MODE_AP && subtype != 0x80 && subtype != 0x40 &&
               subtype != 0x50 && !memcmp(frame + 4, s_peer, 6)) {
        /* A station's auth, (re)association, disassociation or deauthentication to our BSSID. */
        const uint8_t head[2] = {packet->rx_ctrl.channel, (uint8_t)packet->rx_ctrl.rssi};
        wire_send(MSG_RX_MGMT, head, 2, frame, length);
    } else if (subtype == 0x10 && atomic_load(&s_mode) == MODE_STA_JOINING && length >= 28 &&
               !memcmp(frame + 4, s_sta_mac, 6) && !memcmp(frame + 10, s_peer, 6) &&
               frame[26] == 0 && frame[27] == 0) {
        atomic_store(&s_assoc_seen, true);   /* association response, status 0 */
    }
}

static void start_sniffer(void)
{
    const bool sniff = atomic_load(&s_mode) == MODE_SNIFF;
    const wifi_promiscuous_filter_t filter = {
        .filter_mask = WIFI_PROMIS_FILTER_MASK_MGMT |
                       (atomic_load(&s_mode) >= MODE_AP ? WIFI_PROMIS_FILTER_MASK_DATA : 0) |
                       (sniff ? WIFI_PROMIS_FILTER_MASK_CTRL : 0) |
                       ((sniff && s_census) || (atomic_load(&s_mode) == MODE_AP && (s_ap_flags2 & AP_FLAG2_CENSUS))
                            ? WIFI_PROMIS_FILTER_MASK_MISC | WIFI_PROMIS_FILTER_MASK_FCSFAIL |
                              WIFI_PROMIS_FILTER_MASK_CTRL : 0)};
    ESP_ERROR_CHECK(esp_wifi_set_promiscuous_filter(&filter));
    if (sniff || (s_ap_flags2 & AP_FLAG2_CENSUS)) {
        const wifi_promiscuous_filter_t ctrl = {
            .filter_mask = (s_census || !sniff) ? WIFI_PROMIS_CTRL_FILTER_MASK_ALL : WIFI_PROMIS_CTRL_FILTER_MASK_ACK};
        ESP_ERROR_CHECK(esp_wifi_set_promiscuous_ctrl_filter(&ctrl));
    }
    ESP_ERROR_CHECK(esp_wifi_set_promiscuous_rx_cb(promiscuous_rx));
    ESP_ERROR_CHECK(esp_wifi_set_promiscuous(true));
}

static esp_err_t ethernet_rx(void *buffer, uint16_t length, void *eb)
{
    atomic_fetch_add(&s_rx_eth, 1);
    wire_send(MSG_RX_ETH, buffer, length, NULL, 0);
    esp_wifi_internal_free_rx_buffer(eb);
    return ESP_OK;
}

static void tx_done(uint8_t ifidx, uint8_t *data, uint16_t *length, bool acked)
{
    const uint32_t now = (uint32_t)esp_timer_get_time();
    atomic_fetch_add(acked ? &s_tx_acked : &s_tx_unacked, 1);
    const uint16_t n = length ? *length : 0;
    uint32_t queued = UINT32_MAX;
    /* A data frame with a body (not a null function) is one of the host's ETH_TX, in order. */
    if (data && n >= 24 && (data[0] & 0x0c) == 0x08 && !(data[0] & 0x40)) {
        const unsigned tail = atomic_load(&s_tx_handed_tail);
        if (tail != atomic_load(&s_tx_handed_head)) {
            queued = now - s_tx_handed[tail % TX_RING];
            atomic_store(&s_tx_handed_tail, tail + 1);
            if (queued > atomic_load(&s_tx_queued_max_us)) atomic_store(&s_tx_queued_max_us, queued);
            atomic_fetch_add(&s_tx_queued_total_us, queued);
            atomic_fetch_add(&s_tx_queued_n, 1);
        }
    }
    uint8_t head[12];
    memcpy(head, &now, 4);
    memcpy(head + 4, &queued, 4);
    head[8] = acked;
    head[9] = ifidx;
    memcpy(head + 10, &n, 2);
    wire_send(MSG_TX_DONE, head, sizeof(head), data, data ? (n < 24 ? n : 24) : 0);
}

static int ldn_sta_connect(uint8_t *bssid)
{
    /* The stock callback rebuilds the RSN element; install ours on both sides of it. */
    int r = esp_wifi_set_appie_internal(APPIE_RSN, s_rsn_ie, sizeof(s_rsn_ie), 0);
    if (r == 0 && s_stock_sta_connect) r = s_stock_sta_connect(bssid);
    if (r == 0) r = esp_wifi_set_appie_internal(APPIE_RSN, s_rsn_ie, sizeof(s_rsn_ie), 0);
    return r;
}

static void ldn_sta_connected(uint8_t *bssid) { (void)bssid; }
static int ldn_sta_rx_eapol(uint8_t *source, uint8_t *buffer, uint32_t length) { return 0; }
static bool ldn_sta_in_handshake(void) { return false; }

/* Accept the association and answer it, but start no authenticator state machine: the main loop
   installs the pairwise key and opens the port (ap_open_station). */
static bool ldn_ap_join(priv_join_param_t *join)
{
    if (s_ap_flags & AP_FLAG_STOCK_JOIN) return s_stock_ap_join(join);
    struct hostapd_data *hapd = hostapd_get_hapd_data();
    if (!hapd || !join || !join->bssid) return false;
    struct sta_info *sta = ap_get_sta(hapd, join->bssid);
    if (!sta) sta = ap_sta_add(hapd, join->bssid);
    if (!sta) return false;
    if (esp_send_assoc_resp(hapd, join->bssid, 0, true, join->subtype) != 0) return false;
    if (join->pmf_enable) *join->pmf_enable = false;
    if (join->pairwise_cipher) *join->pairwise_cipher = 3;   /* bit of WPA_CIPHER_CCMP */
    *join->sm = sta;
    xQueueSend(s_ap_joins, join->bssid, 0);
    return true;
}

static bool ldn_ap_rx_eapol(void *hapd, void *sm, uint8_t *data, size_t length) { return true; }

/* The beacon and probe response take their RSN element from here; hostapd's own lacks the
   Switch's capabilities 0x000c. */
static uint8_t *ldn_ap_get_wpa_ie(size_t *length)
{
    *length = sizeof(s_rsn_ie);
    return s_rsn_ie;
}

static void install_hooks(void)
{
    struct wpa_funcs *table = malloc(sizeof(*table));
    ESP_ERROR_CHECK(table ? ESP_OK : ESP_ERR_NO_MEM);
    memcpy(table, wpa_cb, sizeof(*table));
    s_stock_sta_connect = table->wpa_sta_connect;
    s_stock_ap_join = table->wpa_ap_join;
    table->wpa_sta_connect = ldn_sta_connect;
    table->wpa_sta_connected_cb = ldn_sta_connected;
    table->wpa_sta_rx_eapol = ldn_sta_rx_eapol;
    table->wpa_sta_in_4way_handshake = ldn_sta_in_handshake;
    table->wpa_ap_join = ldn_ap_join;
    table->wpa_ap_rx_eapol = ldn_ap_rx_eapol;
    table->wpa_ap_get_wpa_ie = ldn_ap_get_wpa_ie;
    ESP_ERROR_CHECK(esp_wifi_register_wpa_cb_internal(table));
    wpa_cb = table;
}

static void go_idle(void)
{
    atomic_store(&s_mode, MODE_IDLE);
    atomic_store(&s_ap_stations, 0);
    atomic_store(&s_tx_handed_tail, atomic_load(&s_tx_handed_head));   /* a new link's frames only */
    esp_wifi_disconnect();
    esp_wifi_stop();
    memset(s_key, 0, sizeof(s_key));
    esp_wifi_set_mode(WIFI_MODE_STA);
    esp_wifi_start();
    esp_wifi_set_ps(WIFI_PS_NONE);
    start_sniffer();
}

static uint8_t s_sta_rate;   /* an index into AP_FIXED_RATES; 0 leaves rate control on */
static uint8_t s_sta_power;  /* esp_wifi_set_max_tx_power units (0.25 dBm, 8..84); 0 leaves it */
static uint8_t s_sta_flags;  /* 1 RTS on every frame, 2 no RTS before a retry */
/* libpp: exported, not in the headers; both read and write lmacConfMib +22 (u16 RTS threshold, 2346)
   and +42 (retries before RTS, 0). docs/hardware_esp32.md */
typedef struct __attribute__((packed)) { uint16_t thr; uint8_t retries_before_rts, cnt_long, cnt_short; } rts_cfg_t;
extern int esp_wifi_internal_set_rts(const void *p);
extern int esp_wifi_internal_get_rts(void *p);

static esp_err_t sta_join(const uint8_t *p, size_t n)
{
    /* Optional: a byte pinning the station's data rate (the AP flag bits 3..5 table), then its
       maximum TX power. docs/hardware_esp32.md */
    if (n < 1 + 6 + 32 + 16 + 6 || n > 1 + 6 + 32 + 16 + 6 + 3) return ESP_ERR_INVALID_SIZE;
    s_sta_rate = n > 61 ? p[61] & 7 : 0;
    s_sta_power = n > 62 ? p[62] : 0;
    s_sta_flags = n > 63 ? p[63] : 0;
    const uint8_t channel = p[0];
    if (channel < 1 || channel > 13 || (p[1] & 1)) return ESP_ERR_INVALID_ARG;
    go_idle();
    memcpy(s_peer, p + 1, 6);
    memcpy(s_key, p + 39, 16);
    memcpy(s_sta_mac, p + 55, 6);
    if (!memcmp(s_sta_mac, "\0\0\0\0\0\0", 6)) {
        esp_fill_random(s_sta_mac, 6);
        s_sta_mac[0] = (s_sta_mac[0] & 0xfc) | 2;
    }
    esp_wifi_stop();
    esp_err_t r = esp_wifi_set_mac(WIFI_IF_STA, s_sta_mac);
#if CONFIG_SOC_WIFI_HE_SUPPORT
    /* An HE station adds Wi-Fi 6 elements to its association request; the other targets send none. */
    if (r == ESP_OK) r = esp_wifi_set_protocol(WIFI_IF_STA, WIFI_PROTOCOL_11B | WIFI_PROTOCOL_11G | WIFI_PROTOCOL_11N);
#endif
    if (r != ESP_OK) return r;
    esp_wifi_start();
    esp_wifi_set_tx_done_cb(tx_done);
    esp_wifi_set_ps(WIFI_PS_NONE);
    start_sniffer();
    wifi_config_t config = {0};
    memcpy(config.sta.ssid, p + 7, 32);
    memcpy(config.sta.password, "00000000", 8);
    memcpy(config.sta.bssid, s_peer, 6);
    config.sta.bssid_set = true;
    config.sta.channel = channel;
    config.sta.scan_method = WIFI_FAST_SCAN;
    config.sta.threshold.authmode = WIFI_AUTH_WPA2_PSK;
    r = esp_wifi_set_config(WIFI_IF_STA, &config);
    if (r != ESP_OK) return r;
    atomic_store(&s_assoc_seen, false);
    s_join_started = esp_timer_get_time();
    atomic_store(&s_mode, MODE_STA_JOINING);
    r = esp_wifi_connect();
    if (r != ESP_OK) atomic_store(&s_mode, MODE_IDLE);
    return r;
}

static void sta_link(bool up, uint16_t reason)
{
    if (!up && reason >= 0xfffe) atomic_fetch_add(&s_led_alarm, 1);
    uint8_t head[9] = {up};
    memcpy(head + 1, &reason, 2);
    memcpy(head + 3, s_sta_mac, 6);
    wire_send(MSG_LINK, head, sizeof(head), NULL, 0);
}

static void sta_install_keys(void)
{
    uint8_t sequence[8] = {0};   /* the pinned blob copies eight RSC bytes */
    const int pairwise = esp_wifi_set_sta_key_internal(WPA_ALG_CCMP, s_peer, 0, 1, sequence, 8, s_key,
                                                       16, KEY_FLAG_PAIRWISE | KEY_FLAG_RX | KEY_FLAG_TX);
    const int group = esp_wifi_set_sta_key_internal(WPA_ALG_CCMP, s_peer, 1, 0, sequence, 8, s_key, 16,
                                                    KEY_FLAG_GROUP | KEY_FLAG_RX);
    if (pairwise || group) {
        wire_log("sta key install failed pairwise=%d group=%d", pairwise, group);
        go_idle();
        sta_link(false, 0xfffe);
        return;
    }
    esp_wifi_auth_done_internal();
    esp_wifi_internal_reg_rxcb(WIFI_IF_STA, ethernet_rx);
    atomic_store(&s_mode, MODE_STA);
    if (s_sta_flags) {
        rts_cfg_t rts = {0};
        const int got = esp_wifi_internal_get_rts(&rts);
        wire_log("sta rts before: %d thr %u retries %u long %u short %u", got, rts.thr, rts.retries_before_rts,
                 rts.cnt_long, rts.cnt_short);
        if (s_sta_flags & 1) rts.thr = 0;
        if (s_sta_flags & 2) rts.retries_before_rts = 255;
        const int set = esp_wifi_internal_set_rts(&rts);
        esp_wifi_internal_get_rts(&rts);
        wire_log("sta rts after: %d thr %u retries %u", set, rts.thr, rts.retries_before_rts);
    }
    if (s_sta_power) {
        int8_t before = 0, after = 0;
        esp_wifi_get_max_tx_power(&before);
        const esp_err_t set = esp_wifi_set_max_tx_power((int8_t)s_sta_power);
        esp_wifi_get_max_tx_power(&after);
        wire_log("sta max tx power %u: %d, %d -> %d", s_sta_power, set, before, after);
    }
    if (s_sta_rate)
        wire_log("sta fixed rate %u: %d", s_sta_rate,
                 esp_wifi_internal_set_fix_rate(WIFI_IF_STA, true, AP_FIXED_RATES[s_sta_rate]));
    sta_link(true, 0);
}

/* libpp: clears g_pm+21, after which pm_noise_check returns before measuring. The check runs every
   NoiseTimerInterval (100) and the receiver misses frames on that cycle. docs/hardware_esp32.md */
extern void pm_noise_check_disable(void);
extern uint16_t NoiseTimerInterval;   /* libpp pp.o .data, 100 */
/* libpp lmac.o: esp_wifi_internal_set_retry_counter(a, b) stores a at +21 and b at +20. */
extern uint8_t lmacConfMib[];
extern int esp_wifi_internal_set_retry_counter(int src, int lrc);

static esp_err_t ap_start(const uint8_t *p, size_t n)
{
    /* Optional: a second flag byte (AP_FLAG2_*), then a maximum TX power in 0.25 dBm. */
    if (n < 1 + 6 + 32 + 16 + 1 + 1 || n > 1 + 6 + 32 + 16 + 1 + 1 + 2) return ESP_ERR_INVALID_SIZE;
    const uint8_t flags2 = n > 57 ? p[57] : 0;
    const uint8_t ap_power = n > 58 ? p[58] : 0;
    s_ap_flags2 = flags2;
    if (flags2 & AP_FLAG2_NOISE_250) NoiseTimerInterval = 250;   /* before the driver arms it */
    const uint8_t channel = p[0];
    if (channel < 1 || channel > 13 || (p[1] & 1)) return ESP_ERR_INVALID_ARG;
    go_idle();
    esp_wifi_stop();
    memcpy(s_peer, p + 1, 6);   /* our BSSID */
    memcpy(s_key, p + 39, 16);
    s_ap_flags = p[56];
    esp_err_t r = esp_wifi_set_mode(WIFI_MODE_AP);
    if (r == ESP_OK) r = esp_wifi_set_mac(WIFI_IF_AP, s_peer);
    /* 11b/g: no HT elements, as a Switch host sends none. docs/hardware_esp32.md */
    if (r == ESP_OK) r = esp_wifi_set_protocol(WIFI_IF_AP, WIFI_PROTOCOL_11B | WIFI_PROTOCOL_11G);
    if (r != ESP_OK) return r;
    wifi_config_t config = {0};
    memcpy(config.ap.ssid, p + 7, 32);
    config.ap.ssid_len = 32;
    memcpy(config.ap.password, "00000000", 8);
    config.ap.channel = channel;
    config.ap.authmode = WIFI_AUTH_WPA2_PSK;
    config.ap.pairwise_cipher = WIFI_CIPHER_TYPE_CCMP;
    config.ap.ssid_hidden = 1;
    config.ap.max_connection = p[55] ? p[55] : 7;
    /* 1000 TU bisects the receive misses against the beacon. docs/hardware_esp32.md */
    config.ap.beacon_interval = (s_ap_flags & AP_FLAG_LONG_BEACON) ? 1000 : 100;
    config.ap.pmf_cfg.required = false;
    r = esp_wifi_set_config(WIFI_IF_AP, &config);
    if (r == ESP_OK) r = esp_wifi_start();
    if (r != ESP_OK) return r;
    esp_wifi_set_tx_done_cb(tx_done);
    esp_wifi_set_ps(WIFI_PS_NONE);
    esp_wifi_set_inactive_time(WIFI_IF_AP, 3600);
    if (flags2 & AP_FLAG2_NO_NOISE_CHECK) {
        pm_noise_check_disable();
        wire_log("ap noise check off");
    }
    if (flags2 & AP_FLAG2_RETRY_7_4) esp_wifi_internal_set_retry_counter(7, 4);   /* 802.11 defaults */
    wire_log("ap noise interval %u", (unsigned)NoiseTimerInterval);
    wire_log("ap lmacConfMib 16..27: %02x %02x %02x %02x %02x %02x %02x %02x %02x %02x %02x %02x",
             lmacConfMib[16], lmacConfMib[17], lmacConfMib[18], lmacConfMib[19], lmacConfMib[20],
             lmacConfMib[21], lmacConfMib[22], lmacConfMib[23], lmacConfMib[24], lmacConfMib[25],
             lmacConfMib[26], lmacConfMib[27]);
    if (AP_FLAG_RATE(s_ap_flags)) {
        const esp_err_t fixed = esp_wifi_internal_set_fix_rate(WIFI_IF_AP, true,
                                                               AP_FIXED_RATES[AP_FLAG_RATE(s_ap_flags)]);
        wire_log("ap fixed rate %u: %d", AP_FLAG_RATE(s_ap_flags), fixed);
    }
    if (ap_power) {
        int8_t before = 0, after = 0;
        esp_wifi_get_max_tx_power(&before);
        const esp_err_t set = esp_wifi_set_max_tx_power((int8_t)ap_power);
        esp_wifi_get_max_tx_power(&after);
        wire_log("ap max tx power %u: %d, %d -> %d", ap_power, set, before, after);
    }
    atomic_store(&s_mode, MODE_AP);
    /* NO_PROMISC bisects the receive misses; no RX_MGMT copies then. docs/hardware_esp32.md */
    if (s_ap_flags & AP_FLAG_NO_PROMISC) esp_wifi_set_promiscuous(false);
    else start_sniffer();
    return ESP_OK;
}

/* esp_wifi_wpa_ptk_init_done_internal opens the port and is what posts AP_STACONNECTED (event 14);
   with no 4-way handshake nothing else calls it. docs/hardware_esp32.md */
/* libnet80211's node table (FreeBSD net80211 layout): ni_flags at +12, bit 1 IEEE80211_NODE_QOS. */
extern void *cnx_node_search(const uint8_t *mac);

static void ap_open_station(const uint8_t *mac)
{
    volatile uint32_t *flags = NULL;
    uint8_t *node = cnx_node_search(mac);
    if (node) flags = (volatile uint32_t *)(node + 12);
    wire_log("ap station node %p flags %08lx", node, flags ? (unsigned long)*flags : 0UL);
    if (flags && (s_ap_flags & AP_FLAG_NO_QOS)) *flags &= ~2u;   /* plain data frames, as a Switch host sends */
    s_ap_pairwise = esp_wifi_set_ap_key_internal(WPA_ALG_CCMP, mac, 0, s_key, 16);
    if (s_ap_pairwise) atomic_fetch_add(&s_led_alarm, 1);
    if (s_ap_pairwise) wire_log("ap pairwise key install failed %d", s_ap_pairwise);
    esp_wifi_wpa_ptk_init_done_internal((uint8_t *)mac);
}

static void wifi_event(void *arg, esp_event_base_t base, int32_t id, void *data)
{
    if (id == WIFI_EVENT_STA_DISCONNECTED) {
        const wifi_event_sta_disconnected_t *event = data;
        const enum mode mode = atomic_load(&s_mode);
        if (mode == MODE_STA || mode == MODE_STA_JOINING) {
            atomic_store(&s_mode, MODE_IDLE);
            sta_link(false, event->reason);
        }
    } else if (id == WIFI_EVENT_AP_START) {
        const int group = esp_wifi_set_ap_key_internal(WPA_ALG_CCMP, BROADCAST, 1, s_key, 16);
        esp_wifi_internal_reg_rxcb(WIFI_IF_AP, ethernet_rx);
        uint8_t head[9] = {1};
        memcpy(head + 3, s_peer, 6);
        if (group) { head[0] = 0; atomic_fetch_add(&s_led_alarm, 1); wire_log("ap group key install failed %d", group); }
        wire_send(MSG_LINK, head, sizeof(head), NULL, 0);
    } else if (id == WIFI_EVENT_AP_STACONNECTED) {
        const wifi_event_ap_staconnected_t *event = data;
        uint8_t head[9];
        memcpy(head, event->mac, 6);
        head[6] = event->aid;
        head[7] = (uint8_t)s_ap_pairwise;
        head[8] = 1;
        atomic_fetch_add(&s_ap_stations, 1);
        wire_send(MSG_STA_JOINED, head, sizeof(head), NULL, 0);
    } else if (id == WIFI_EVENT_AP_STADISCONNECTED) {
        const wifi_event_ap_stadisconnected_t *event = data;
        uint8_t head[8];
        memcpy(head, event->mac, 6);
        memcpy(head + 6, &event->reason, 2);
        if (atomic_fetch_sub(&s_ap_stations, 1) <= 0) atomic_store(&s_ap_stations, 0);
        wire_send(MSG_STA_LEFT, head, sizeof(head), NULL, 0);
    }
}

/* A BOOT press: u32 board time in µs, u16 press count, for the host's trace. */
static void button_pressed(uint32_t count, int64_t press_us)
{
    uint8_t head[6];
    const uint32_t us = (uint32_t)press_us;
    const uint16_t n = (uint16_t)count;
    atomic_store(&s_presses, count);
    memcpy(head, &us, 4);
    memcpy(head + 4, &n, 2);
    wire_send(MSG_BUTTON, head, sizeof(head), NULL, 0);
}

/* The automatic look by mode: docs/hardware_esp32.md, The board's LED and buttons. */
static void led_state(led_look_t *look, uint32_t *activity, uint32_t *alarm)
{
    switch (atomic_load(&s_mode)) {
    case MODE_IDLE: *look = (led_look_t){LED_BREATHE, 50, 4000}; break;
    case MODE_STA_JOINING: *look = (led_look_t){LED_BLINK, 255, 250}; break;
    case MODE_AP:
        if (atomic_load(&s_ap_stations) <= 0) { *look = (led_look_t){LED_BREATHE, 110, 1500}; break; }
        __attribute__((fallthrough));   /* a seated console looks like a joined one */
    case MODE_STA: *look = (led_look_t){LED_ON, 25, 0}; break;
    case MODE_SNIFF: *look = (led_look_t){LED_OFF, 0, 0}; break;
    }
    *activity = atomic_load(&s_rx_eth) + atomic_load(&s_tx_acked) + atomic_load(&s_tx_unacked) +
                atomic_load(&s_rx_sniff);
    *alarm = atomic_load(&s_led_alarm) + wire_dropped() + wire_rx_bad() + wire_rx_fifo_ovf() +
             wire_rx_buffer_full();
}

static void display_state(scene_radio_t *state)
{
    static const uint8_t SCENES[] = {
        [MODE_IDLE] = SCENE_IDLE, [MODE_STA_JOINING] = SCENE_JOINING, [MODE_STA] = SCENE_JOINED,
        [MODE_AP] = SCENE_HOSTING, [MODE_SNIFF] = SCENE_SNIFFING,
    };
    state->mode = SCENES[atomic_load(&s_mode)];
    const int stations = atomic_load(&s_ap_stations);
    state->stations = stations > 0 ? (uint8_t)stations : 0;
    state->rx = atomic_load(&s_rx_eth);
    state->tx = atomic_load(&s_tx_acked) + atomic_load(&s_tx_unacked);
    state->presses = atomic_load(&s_presses);
}

static void send_status(void)
{
    char text[768];
    int len = snprintf(text, sizeof(text),
        "mode=%d rx_mgmt=%u rx_eth=%u tx_eth=%u tx_eth_failed=%u tx_raw=%u tx_raw_failed=%u "
        "wire_dropped=%u heap=%u tx_acked=%u tx_unacked=%u tx_eth_retried=%u tx_eth_last_err=%#x "
        "wire_rx_bad=%u uart_overflow=%u uart_fifo_ovf=%u uart_buffer_full=%u uart_frame_err=%u "
        "uart_events_full=%u "
        "tx_eth_max_us=%u tx_eth_total_us=%u tx_eth_slow=%u "
        "tx_queued_max_us=%u tx_queued_total_us=%u tx_queued_n=%u tx_queued_pending=%u",
        (int)atomic_load(&s_mode), atomic_load(&s_rx_mgmt), atomic_load(&s_rx_eth),
        atomic_load(&s_tx_eth), atomic_load(&s_tx_eth_failed), atomic_load(&s_tx_raw),
        atomic_load(&s_tx_raw_failed), (unsigned)wire_dropped(),
        (unsigned)esp_get_free_heap_size(), atomic_load(&s_tx_acked), atomic_load(&s_tx_unacked),
        atomic_load(&s_tx_eth_retried), (unsigned)atomic_load(&s_tx_eth_last_err),
        (unsigned)wire_rx_bad(), (unsigned)(wire_rx_fifo_ovf() + wire_rx_buffer_full()),
        (unsigned)wire_rx_fifo_ovf(), (unsigned)wire_rx_buffer_full(),
        (unsigned)wire_rx_frame_err(), (unsigned)wire_events_full(),
        atomic_load(&s_tx_eth_max_us), atomic_load(&s_tx_eth_total_us), atomic_load(&s_tx_eth_slow),
        atomic_load(&s_tx_queued_max_us), atomic_load(&s_tx_queued_total_us),
        atomic_load(&s_tx_queued_n),
        atomic_load(&s_tx_handed_head) - atomic_load(&s_tx_handed_tail));
    if (len < 0) return;
    if (len < (int)sizeof(text) - 1) {
        text[len++] = ' ';
        const int more = wire_stats(text + len, sizeof(text) - len);
        if (more > 0) len += more;
    }
    if (len >= (int)sizeof(text)) len = sizeof(text) - 1;
    wire_send(MSG_STATUS, text, len, NULL, 0);
}

/* BENCH: u32 bytes, u16 message size. Random payloads, each led by a u32 sequence, then one led by
   0xffffffff carrying the board's microseconds; nothing is dropped. docs/hardware_esp32.md */
static void bench_task(void *arg)
{
    const uint32_t total = ((uint32_t *)arg)[0], size = ((uint32_t *)arg)[1];
    free(arg);
    static uint8_t body[WIRE_MAX_PAYLOAD];
    const int64_t started = esp_timer_get_time();
    uint32_t seq = 0;
    /* Filled once: a fill per message held BENCH under the 1500000 line's rate, so its queue never
       backed up the way a console's flood backs it up. */
    esp_fill_random(body, sizeof(body));
    for (uint32_t sent = 0; sent < total; sent += size, ++seq) {
        memcpy(body, &seq, 4);
        while (!wire_send_wait(MSG_BENCH, NULL, 0, body, size, pdMS_TO_TICKS(100))) {}
    }
    const uint32_t done[2] = {UINT32_MAX, (uint32_t)(esp_timer_get_time() - started)};
    while (!wire_send_wait(MSG_BENCH, NULL, 0, done, sizeof(done), pdMS_TO_TICKS(100))) {}
    vTaskDelete(NULL);
}

static void send_info(void)
{
    uint8_t head[1 + 6 + 6 + 1];
    esp_chip_info_t chip;
    esp_chip_info(&chip);
    head[0] = PROTOCOL_VERSION;
    esp_wifi_get_mac(WIFI_IF_STA, head + 1);
    esp_read_mac(head + 7, ESP_MAC_WIFI_SOFTAP);
    head[13] = (uint8_t)(chip.revision / 100);
    char text[128];
    snprintf(text, sizeof(text), "pokeldn-radio " CONFIG_IDF_TARGET " version=%s idf=" IDF_VER,
             esp_app_get_description()->version);
    wire_send(MSG_INFO, head, sizeof(head), text, strlen(text));
    usbwatch_report();
}

static _Atomic int64_t s_host_seen;   /* when the host last sent a command */
static atomic_bool s_host_watched;    /* armed by CMD_ALIVE, disarmed by HELLO: an older host never sends it */

static void command(uint8_t type, const uint8_t *p, size_t n)
{
    atomic_store(&s_host_seen, esp_timer_get_time());
    wire_set_host_away(false);
    switch (type) {
    case CMD_HELLO: atomic_store(&s_host_watched, false); wire_credit_reset(); display_reset(); send_info(); break;
    case CMD_ALIVE: atomic_store(&s_host_watched, true); break;   /* no reply: it only keeps the watch fed */
    case CMD_BAUD: {
        uint32_t baud;
        if (n != 4) { result(type, ESP_ERR_INVALID_SIZE); break; }
        memcpy(&baud, p, 4);
        result(type, 0);
        wire_set_baud(baud);   /* queued behind the RESULT, which leaves at the old rate */
        break;
    }
    case CMD_CHANNEL:
        if (n != 1 || atomic_load(&s_mode) != MODE_IDLE) { result(type, ESP_ERR_INVALID_STATE); break; }
        result(type, esp_wifi_set_channel(p[0], WIFI_SECOND_CHAN_NONE));
        break;
    case CMD_SNIFF:   /* u8 channel, 6 MAC */
        if (n != 7) { result(type, ESP_ERR_INVALID_SIZE); break; }
        go_idle();
        memcpy(s_sniff_mac, p + 1, 6);
        s_census = !memcmp(s_sniff_mac, "\xff\xff\xff\xff\xff\xff", 6);
        {
            const esp_err_t r = esp_wifi_set_channel(p[0], WIFI_SECOND_CHAN_NONE);
            if (r == ESP_OK) { atomic_store(&s_mode, MODE_SNIFF); start_sniffer(); }
            result(type, r);
        }
        break;
    case CMD_STA_JOIN: result(type, sta_join(p, n)); break;
    case CMD_STOP: go_idle(); result(type, 0); break;
    case CMD_AP_START: result(type, ap_start(p, n)); break;
    case CMD_AP_KICK: {
        if (n != 8) { result(type, ESP_ERR_INVALID_SIZE); break; }
        uint8_t mac[6];
        uint16_t reason;
        memcpy(mac, p, 6);
        memcpy(&reason, p + 6, 2);
        result(type, esp_wifi_ap_deauth_internal(mac, reason));
        break;
    }
    case CMD_ETH_TX: {
        static uint8_t frame[1600];
        const enum mode mode = atomic_load(&s_mode);
        int r = ESP_ERR_INVALID_STATE;
        if ((mode == MODE_STA || mode == MODE_AP) && n >= 14 && n <= sizeof(frame)) {
            memcpy(frame, p, n);
            const int64_t started = esp_timer_get_time();
            /* Published before the call: its TX-done can run on the other core before it returns. */
            s_tx_handed[atomic_load(&s_tx_handed_head) % TX_RING] = (uint32_t)started;
            atomic_fetch_add(&s_tx_handed_head, 1);
            r = esp_wifi_internal_tx(current_interface(), frame, n);
            /* A full driver queue is retried rather than dropped; a station that left gives 0x3015
               at once. docs/hardware_esp32.md */
            for (int tries = 0; r == ESP_ERR_NO_MEM && tries < 100; ++tries) {
                if (tries == 0) atomic_fetch_add(&s_tx_eth_retried, 1);
                vTaskDelay(1);
                r = esp_wifi_internal_tx(current_interface(), frame, n);
            }
            const uint32_t took = esp_timer_get_time() - started;
            if (took > atomic_load(&s_tx_eth_max_us)) atomic_store(&s_tx_eth_max_us, took);
            atomic_fetch_add(&s_tx_eth_total_us, took);   /* wraps after 71 min */
            if (took > 5000) atomic_fetch_add(&s_tx_eth_slow, 1);
            if (r != ESP_OK) atomic_fetch_sub(&s_tx_handed_head, 1);   /* no TX-done will come */
        }
        if (r != ESP_OK) atomic_store(&s_tx_eth_last_err, r);
        atomic_fetch_add(r == ESP_OK ? &s_tx_eth : &s_tx_eth_failed, 1);
        break;
    }
    case CMD_RAW_TX: {
        const int r = n >= 24 && n <= 1500 ? esp_wifi_80211_tx(current_interface(), p, n, true)
                                           : ESP_ERR_INVALID_SIZE;
        atomic_fetch_add(r == ESP_OK ? &s_tx_raw : &s_tx_raw_failed, 1);
        break;
    }
    case CMD_STATUS: send_status(); break;
    case CMD_BENCH: {
        uint32_t *arg = malloc(8);
        uint16_t size;
        if (n != 6 || !arg) { free(arg); result(type, ESP_ERR_INVALID_SIZE); break; }
        memcpy(&arg[0], p, 4);
        memcpy(&size, p + 4, 2);
        arg[1] = size;
        if (size < 8 || size > WIRE_MAX_PAYLOAD) { free(arg); result(type, ESP_ERR_INVALID_ARG); break; }
        result(type, 0);
        xTaskCreatePinnedToCore(bench_task, "bench", 3072, arg, 5, NULL, 0);
        break;
    }
    case CMD_LED: {   /* u8 pattern, u8 peak, u16 period ms, u16 duration ms */
        uint16_t period, duration;
        if (n != 6) { result(type, ESP_ERR_INVALID_SIZE); break; }
        memcpy(&period, p + 2, 2);
        memcpy(&duration, p + 4, 2);
        result(type, led_set(p[0], p[1], period, duration) ? 0 : ESP_ERR_INVALID_ARG);
        break;
    }
    case CMD_DISPLAY:   /* scene.h; ESP_ERR_NOT_FOUND without a screen */
        result(type, display_command(p, n) ? 0 : ESP_ERR_NOT_FOUND);
        break;
    default: result(type, ESP_ERR_NOT_SUPPORTED);
    }
}

#if CONFIG_IDF_TARGET_ESP32C6
/* XIAO ESP32C6: GPIO3 low powers the RF switch, GPIO14 low picks the ceramic antenna and high the
   U.FL socket (Seeed's board guide). docs/hardware_esp32.md, Supported boards. */
static void rf_switch_on(void)
{
    const gpio_config_t out = {.pin_bit_mask = (1ULL << 3) | (1ULL << 14), .mode = GPIO_MODE_OUTPUT};
    gpio_config(&out);
    gpio_set_level(3, 0);
    gpio_set_level(14, 0);
}
#endif

void app_main(void)
{
#if CONFIG_IDF_TARGET_ESP32C6
    rf_switch_on();
#endif
    esp_err_t r = nvs_flash_init();
    if (r == ESP_ERR_NVS_NO_FREE_PAGES || r == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        ESP_ERROR_CHECK(nvs_flash_erase());
        r = nvs_flash_init();
    }
    ESP_ERROR_CHECK(r);
    ESP_ERROR_CHECK(esp_event_loop_create_default());
    const wifi_init_config_t init = WIFI_INIT_CONFIG_DEFAULT();
    ESP_ERROR_CHECK(esp_wifi_init(&init));
    ESP_ERROR_CHECK(esp_wifi_set_storage(WIFI_STORAGE_RAM));
    ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_STA));
    s_ap_joins = xQueueCreate(8, 6);
    install_hooks();
    ESP_ERROR_CHECK(esp_event_handler_register(WIFI_EVENT, ESP_EVENT_ANY_ID, wifi_event, NULL));
    ESP_ERROR_CHECK(esp_wifi_start());
    esp_wifi_set_ps(WIFI_PS_NONE);
    start_sniffer();
    wire_start(command);
    usbwatch_start();
    led_start(led_state, button_pressed);
    display_start(display_state);
    send_info();

    int64_t last_status = 0;
    for (;;) {
        if (atomic_load(&s_mode) == MODE_AP && esp_timer_get_time() - last_status > 2000000) {
            last_status = esp_timer_get_time();
            send_status();
        }
        uint8_t joined[6];
        while (xQueueReceive(s_ap_joins, joined, 0) == pdTRUE) {
            if (atomic_load(&s_mode) == MODE_AP) ap_open_station(joined);
        }
        if (atomic_load(&s_host_watched) && atomic_load(&s_mode) != MODE_IDLE &&
            esp_timer_get_time() - atomic_load(&s_host_seen) > HOST_SILENT_US) {
            atomic_store(&s_host_watched, false);
            go_idle();
            wire_set_host_away(true);   /* its queue and what is heard next go nowhere: no alarm */
        }
        if (atomic_load(&s_mode) == MODE_STA_JOINING) {
            if (atomic_load(&s_assoc_seen) && esp_wifi_sta_is_running_internal()) {
                sta_install_keys();
            } else if (esp_timer_get_time() - s_join_started > 15000000) {
                go_idle();
                sta_link(false, 0xffff);
            }
        }
        vTaskDelay(1);
    }
}
