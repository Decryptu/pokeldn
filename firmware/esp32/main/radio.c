/* pokeldn radio: an ESP32 as the LDN radio of a host on USB serial.

   The board carries Ethernet frames and LDN's vendor action frames; everything above them
   (advertisement crypto, LDN authentication, IP, Pia) runs on the host. A station joins a
   console's network with the host's derived CCMP key; an access point takes a console's
   association without the 4-way handshake and installs the same key for it.
   docs/hardware_esp32.md has the message set. */
#include <stdatomic.h>
#include <string.h>

#include "esp_chip_info.h"
#include "esp_event.h"
#include "esp_mac.h"
#include "esp_private/wifi.h"
#include "esp_random.h"
#include "esp_timer.h"
#include "esp_wifi.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "nvs_flash.h"

#include "private_wifi.h"
#include "wire.h"

#define PROTOCOL_VERSION 1

enum {
    CMD_HELLO = 0x01, CMD_BAUD = 0x02, CMD_CHANNEL = 0x03, CMD_STA_JOIN = 0x04, CMD_STOP = 0x05,
    CMD_AP_START = 0x06, CMD_AP_KICK = 0x07, CMD_ETH_TX = 0x08, CMD_RAW_TX = 0x09,
    CMD_STATUS = 0x0B,
};
enum {
    MSG_INFO = 0x81, MSG_RESULT = 0x82, MSG_RX_MGMT = 0x84, MSG_RX_ETH = 0x85, MSG_LINK = 0x86,
    MSG_STA_JOINED = 0x87, MSG_STA_LEFT = 0x88, MSG_STATUS = 0x89,
};
enum { AP_FLAG_STOCK_JOIN = 1 };
enum mode { MODE_IDLE, MODE_STA_JOINING, MODE_STA, MODE_AP };

static const uint8_t BROADCAST[6] = {0xff, 0xff, 0xff, 0xff, 0xff, 0xff};
static const uint8_t LDN_ACTION[4] = {0x7f, 0x00, 0x22, 0xaa};

/* The RSN element a Switch station sends: CCMP, PSK, capabilities 0x000c. */
static uint8_t s_rsn_ie[] = {
    0x30, 0x14, 0x01, 0x00, 0x00, 0x0f, 0xac, 0x04, 0x01, 0x00, 0x00, 0x0f, 0xac, 0x04,
    0x01, 0x00, 0x00, 0x0f, 0xac, 0x02, 0x0c, 0x00,
};

static _Atomic enum mode s_mode = MODE_IDLE;
static uint8_t s_key[16], s_peer[6], s_sta_mac[6];
static uint8_t s_ap_flags;
static int64_t s_join_started;
static atomic_bool s_assoc_seen;
static atomic_uint s_rx_mgmt, s_rx_eth, s_tx_eth, s_tx_eth_failed, s_tx_raw, s_tx_raw_failed;
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

/* ---- receive paths ---- */

static void promiscuous_rx(void *buffer, wifi_promiscuous_pkt_type_t type)
{
    if (type != WIFI_PKT_MGMT) return;
    const wifi_promiscuous_pkt_t *packet = buffer;
    const uint8_t *frame = packet->payload;
    const int length = (int)packet->rx_ctrl.sig_len - 4;   /* sig_len counts the FCS */
    if (length < 24) return;
    const uint8_t subtype = frame[0] & 0xfc;
    if (subtype == 0xd0 && length >= 24 + 4 && !memcmp(frame + 24, LDN_ACTION, 4)) {
        const uint8_t head[2] = {packet->rx_ctrl.channel, (uint8_t)packet->rx_ctrl.rssi};
        atomic_fetch_add(&s_rx_mgmt, 1);
        wire_send(MSG_RX_MGMT, head, 2, frame, length);
    } else if (subtype == 0x10 && atomic_load(&s_mode) == MODE_STA_JOINING && length >= 28 &&
               !memcmp(frame + 4, s_sta_mac, 6) && !memcmp(frame + 10, s_peer, 6) &&
               frame[26] == 0 && frame[27] == 0) {
        atomic_store(&s_assoc_seen, true);   /* association response, status 0 */
    }
}

static void start_sniffer(void)
{
    const wifi_promiscuous_filter_t filter = {.filter_mask = WIFI_PROMIS_FILTER_MASK_MGMT};
    ESP_ERROR_CHECK(esp_wifi_set_promiscuous_filter(&filter));
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

/* ---- WPA hooks: LDN has no 4-way handshake; the key comes from the host ---- */

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

/* Accept the association and answer it, but start no authenticator state machine: the pairwise
   key is installed from the AP_STACONNECTED event instead. */
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

/* ---- modes ---- */

static void go_idle(void)
{
    atomic_store(&s_mode, MODE_IDLE);
    esp_wifi_disconnect();
    esp_wifi_stop();
    memset(s_key, 0, sizeof(s_key));
    esp_wifi_set_mode(WIFI_MODE_STA);
    esp_wifi_start();
    esp_wifi_set_ps(WIFI_PS_NONE);
    start_sniffer();
}

static esp_err_t sta_join(const uint8_t *p, size_t n)
{
    if (n != 1 + 6 + 32 + 16 + 6) return ESP_ERR_INVALID_SIZE;
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
    if (r != ESP_OK) return r;
    esp_wifi_start();
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
    sta_link(true, 0);
}

static esp_err_t ap_start(const uint8_t *p, size_t n)
{
    if (n != 1 + 6 + 32 + 16 + 1 + 1) return ESP_ERR_INVALID_SIZE;
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
    config.ap.beacon_interval = 100;
    config.ap.pmf_cfg.required = false;
    r = esp_wifi_set_config(WIFI_IF_AP, &config);
    if (r == ESP_OK) r = esp_wifi_start();
    if (r != ESP_OK) return r;
    esp_wifi_set_ps(WIFI_PS_NONE);
    esp_wifi_set_inactive_time(WIFI_IF_AP, 3600);
    start_sniffer();
    atomic_store(&s_mode, MODE_AP);
    return ESP_OK;
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
        if (group) { head[0] = 0; wire_log("ap group key install failed %d", group); }
        wire_send(MSG_LINK, head, sizeof(head), NULL, 0);
    } else if (id == WIFI_EVENT_AP_STACONNECTED) {
        const wifi_event_ap_staconnected_t *event = data;
        uint8_t mac[6];
        memcpy(mac, event->mac, 6);
        const int pairwise = esp_wifi_set_ap_key_internal(WPA_ALG_CCMP, mac, 0, s_key, 16);
        const bool opened = esp_wifi_wpa_ptk_init_done_internal(mac);
        uint8_t head[9];
        memcpy(head, mac, 6);
        head[6] = event->aid;
        head[7] = (uint8_t)pairwise;
        head[8] = opened;
        wire_send(MSG_STA_JOINED, head, sizeof(head), NULL, 0);
    } else if (id == WIFI_EVENT_AP_STADISCONNECTED) {
        const wifi_event_ap_stadisconnected_t *event = data;
        uint8_t head[8];
        memcpy(head, event->mac, 6);
        memcpy(head + 6, &event->reason, 2);
        wire_send(MSG_STA_LEFT, head, sizeof(head), NULL, 0);
    }
}

/* ---- host commands ---- */

static void send_info(void)
{
    uint8_t head[1 + 6 + 6 + 1];
    esp_chip_info_t chip;
    esp_chip_info(&chip);
    head[0] = PROTOCOL_VERSION;
    esp_wifi_get_mac(WIFI_IF_STA, head + 1);
    esp_read_mac(head + 7, ESP_MAC_WIFI_SOFTAP);
    head[13] = (uint8_t)(chip.revision / 100);
    const char *text = "pokeldn-radio " CONFIG_IDF_TARGET " idf=" IDF_VER;
    wire_send(MSG_INFO, head, sizeof(head), text, strlen(text));
}

static void command(uint8_t type, const uint8_t *p, size_t n)
{
    switch (type) {
    case CMD_HELLO: send_info(); break;
    case CMD_BAUD: {
        uint32_t baud;
        if (n != 4) { result(type, ESP_ERR_INVALID_SIZE); break; }
        memcpy(&baud, p, 4);
        result(type, 0);
        wire_set_baud(baud);
        break;
    }
    case CMD_CHANNEL:
        if (n != 1 || atomic_load(&s_mode) != MODE_IDLE) { result(type, ESP_ERR_INVALID_STATE); break; }
        result(type, esp_wifi_set_channel(p[0], WIFI_SECOND_CHAN_NONE));
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
            r = esp_wifi_internal_tx(current_interface(), frame, n);
        }
        atomic_fetch_add(r == ESP_OK ? &s_tx_eth : &s_tx_eth_failed, 1);
        break;
    }
    case CMD_RAW_TX: {
        const int r = n >= 24 && n <= 1500 ? esp_wifi_80211_tx(current_interface(), p, n, true)
                                           : ESP_ERR_INVALID_SIZE;
        atomic_fetch_add(r == ESP_OK ? &s_tx_raw : &s_tx_raw_failed, 1);
        break;
    }
    case CMD_STATUS: {
        char text[200];
        const int len = snprintf(text, sizeof(text),
            "mode=%d rx_mgmt=%u rx_eth=%u tx_eth=%u tx_eth_failed=%u tx_raw=%u tx_raw_failed=%u "
            "wire_dropped=%u heap=%u",
            (int)atomic_load(&s_mode), atomic_load(&s_rx_mgmt), atomic_load(&s_rx_eth),
            atomic_load(&s_tx_eth), atomic_load(&s_tx_eth_failed), atomic_load(&s_tx_raw),
            atomic_load(&s_tx_raw_failed), (unsigned)wire_dropped(),
            (unsigned)esp_get_free_heap_size());
        wire_send(MSG_STATUS, text, len, NULL, 0);
        break;
    }
    default: result(type, ESP_ERR_NOT_SUPPORTED);
    }
}

void app_main(void)
{
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
    install_hooks();
    ESP_ERROR_CHECK(esp_event_handler_register(WIFI_EVENT, ESP_EVENT_ANY_ID, wifi_event, NULL));
    ESP_ERROR_CHECK(esp_wifi_start());
    esp_wifi_set_ps(WIFI_PS_NONE);
    start_sniffer();
    wire_start(command);
    send_info();

    for (;;) {
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
