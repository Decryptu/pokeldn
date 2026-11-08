/* Wi-Fi: a station on the stored network. With none stored, or none joined within 20 s, a setup
   access point (POKELDN-BRIDGE-XXXX, WPA2 password pokeldn-bridge, http://192.168.4.1) opens beside
   the station's retries; a phone joining it is sent to the setup page by the captive DNS. After the
   station joins, the access point stays up a minute so the page can show the new address. */
#include "bridge.h"

#include <stdio.h>
#include <string.h>

#include "esp_event.h"
#include "esp_log.h"
#include "esp_mac.h"
#include "esp_netif.h"
#include "esp_timer.h"
#include "esp_wifi.h"
#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"
#include "nvs.h"

#define SETUP_PASSWORD "pokeldn-bridge"
#define HOSTNAME "pokeldn-bridge"
#define FALLBACK_US (20 * 1000000LL)   /* no address this long: open the access point */
#define AP_LINGER_US (60 * 1000000LL)  /* joined: keep the access point this long */
#define RETRY_US (3 * 1000000LL)
#define RETRY_SETUP_US (15 * 1000000LL)   /* a station's scan takes the channel from setup's clients */

static const char *TAG = "net";

static esp_netif_t *s_sta, *s_ap;
static SemaphoreHandle_t s_lock;
static char s_ssid[33], s_password[65];
static char s_pending_ssid[33], s_pending_password[65];
static char s_ap_ssid[33];
static volatile bool s_ap_up, s_online, s_started, s_scanning;
static esp_ip4_addr_t s_ip;
static esp_timer_handle_t s_retry, s_fallback, s_linger, s_apply;
static bool s_force_5g;   /* stored under "band"; applies from the next start */

/* Forced to 5 GHz, the station joins only a 5 GHz network and leaves 2.4 GHz to the radio and the
   console. The setup access point is on 2.4 GHz channel 1, so it lifts the force while it is open:
   a bridge whose network has no 5 GHz band stays reachable. */
static void set_band(void)
{
#if CONFIG_SOC_WIFI_SUPPORT_5G
    esp_wifi_set_band_mode(s_force_5g && !s_ap_up ? WIFI_BAND_MODE_5G_ONLY : WIFI_BAND_MODE_AUTO);
#endif
}

static void set_ap(bool up)
{
    if (up == s_ap_up) return;
    s_ap_up = up;
    esp_wifi_set_mode(up ? WIFI_MODE_APSTA : WIFI_MODE_STA);
    set_band();
    if (up) captive_start(); else captive_stop();
    ESP_LOGI(TAG, "setup access point %s", up ? "open" : "closed");
}

static void connect_station(void)
{
    if (!s_ssid[0] || s_scanning) return;
    wifi_config_t config = {0};
    memcpy(config.sta.ssid, s_ssid, strlen(s_ssid));
    memcpy(config.sta.password, s_password, strlen(s_password));
    config.sta.threshold.authmode = s_password[0] ? WIFI_AUTH_WPA2_PSK : WIFI_AUTH_OPEN;
    config.sta.scan_method = WIFI_ALL_CHANNEL_SCAN;
    config.sta.sort_method = WIFI_CONNECT_AP_BY_SIGNAL;
    esp_wifi_set_config(WIFI_IF_STA, &config);
    esp_wifi_connect();
}

static void retry(void *arg) { connect_station(); }

static void fallback(void *arg)
{
    if (!s_online) set_ap(true);
}

static void linger(void *arg)
{
    if (s_online) set_ap(false);
}

static void load(void)
{
    nvs_handle_t nvs;
    if (nvs_open("net", NVS_READONLY, &nvs) != ESP_OK) return;
    size_t size = sizeof(s_ssid);
    if (nvs_get_str(nvs, "ssid", s_ssid, &size) != ESP_OK) s_ssid[0] = 0;
    size = sizeof(s_password);
    if (nvs_get_str(nvs, "password", s_password, &size) != ESP_OK) s_password[0] = 0;
    nvs_close(nvs);
}

static void load_band(void)
{
    nvs_handle_t nvs;
    if (nvs_open("band", NVS_READONLY, &nvs) != ESP_OK) return;
    uint8_t force = 0;
    nvs_get_u8(nvs, "force5g", &force);
    s_force_5g = force && net_can_5g();
    nvs_close(nvs);
}

bool net_can_5g(void)
{
#if CONFIG_SOC_WIFI_SUPPORT_5G
    return true;
#else
    return false;
#endif
}

bool net_force_5g(void) { return s_force_5g; }

void net_set_force_5g(bool force)
{
    nvs_handle_t nvs;
    if (nvs_open("band", NVS_READWRITE, &nvs) != ESP_OK) return;
    nvs_set_u8(nvs, "force5g", force && net_can_5g());
    nvs_commit(nvs);
    nvs_close(nvs);
}

static void store(void)
{
    nvs_handle_t nvs;
    if (nvs_open("net", NVS_READWRITE, &nvs) != ESP_OK) return;
    if (s_ssid[0]) {
        nvs_set_str(nvs, "ssid", s_ssid);
        nvs_set_str(nvs, "password", s_password);
    } else {
        nvs_erase_all(nvs);
    }
    nvs_commit(nvs);
    nvs_close(nvs);
}

/* Runs half a second after the request, so the page gets its answer before the station drops. */
static void apply(void *arg)
{
    xSemaphoreTake(s_lock, portMAX_DELAY);
    snprintf(s_ssid, sizeof(s_ssid), "%s", s_pending_ssid);
    snprintf(s_password, sizeof(s_password), "%s", s_pending_password);
    xSemaphoreGive(s_lock);
    store();
    esp_timer_stop(s_retry);
    esp_timer_stop(s_linger);
    s_online = false;
    esp_wifi_disconnect();
    if (!s_ssid[0]) {
        ESP_LOGI(TAG, "network forgotten");
        set_ap(true);
        return;
    }
    ESP_LOGI(TAG, "joining %s", s_ssid);
    connect_station();
    esp_timer_stop(s_fallback);
    esp_timer_start_once(s_fallback, FALLBACK_US);
}

void net_configure(const char *ssid, const char *password)
{
    xSemaphoreTake(s_lock, portMAX_DELAY);
    snprintf(s_pending_ssid, sizeof(s_pending_ssid), "%s", ssid);
    snprintf(s_pending_password, sizeof(s_pending_password), "%s", password);
    xSemaphoreGive(s_lock);
    esp_timer_stop(s_apply);
    esp_timer_start_once(s_apply, 500000);
}

static void on_event(void *arg, esp_event_base_t base, int32_t id, void *data)
{
    if (base == WIFI_EVENT && id == WIFI_EVENT_STA_START) {
        s_started = true;
        connect_station();
    } else if (base == WIFI_EVENT && id == WIFI_EVENT_STA_DISCONNECTED) {
        const wifi_event_sta_disconnected_t *event = data;
        if (s_online) ESP_LOGW(TAG, "left %s, reason %d", s_ssid, event->reason);
        const bool was_online = s_online;
        s_online = false;
        s_ip.addr = 0;
        if (!s_ssid[0] || s_scanning) return;
        esp_timer_stop(s_retry);
        esp_timer_start_once(s_retry, s_ap_up ? RETRY_SETUP_US : RETRY_US);
        if (was_online) {
            esp_timer_stop(s_fallback);
            esp_timer_start_once(s_fallback, FALLBACK_US);
        }
    } else if (base == IP_EVENT && id == IP_EVENT_STA_GOT_IP) {
        const ip_event_got_ip_t *event = data;
        s_ip = event->ip_info.ip;
        s_online = true;
        esp_wifi_set_ps(WIFI_PS_NONE);
        ESP_LOGI(TAG, "joined %s as " IPSTR, s_ssid, IP2STR(&s_ip));
        esp_timer_stop(s_fallback);
        if (s_ap_up) {
            esp_timer_stop(s_linger);
            esp_timer_start_once(s_linger, AP_LINGER_US);
        }
    }
}

void net_start(void)
{
    s_lock = xSemaphoreCreateMutex();
    load();
    load_band();
    ESP_ERROR_CHECK(esp_netif_init());
    ESP_ERROR_CHECK(esp_event_loop_create_default());
    s_sta = esp_netif_create_default_wifi_sta();
    s_ap = esp_netif_create_default_wifi_ap();
    esp_netif_set_hostname(s_sta, HOSTNAME);   /* a router's DNS may then know pokeldn-bridge */

    const wifi_init_config_t init = WIFI_INIT_CONFIG_DEFAULT();
    ESP_ERROR_CHECK(esp_wifi_init(&init));
    ESP_ERROR_CHECK(esp_wifi_set_storage(WIFI_STORAGE_RAM));
    ESP_ERROR_CHECK(esp_event_handler_register(WIFI_EVENT, ESP_EVENT_ANY_ID, on_event, NULL));
    ESP_ERROR_CHECK(esp_event_handler_register(IP_EVENT, IP_EVENT_STA_GOT_IP, on_event, NULL));

    uint8_t mac[6];
    esp_read_mac(mac, ESP_MAC_WIFI_SOFTAP);
    snprintf(s_ap_ssid, sizeof(s_ap_ssid), "POKELDN-BRIDGE-%02X%02X", mac[4], mac[5]);
    wifi_config_t ap = {
        .ap = {.channel = 1, .max_connection = 4, .authmode = WIFI_AUTH_WPA2_PSK,
               .pmf_cfg = {.required = false}},
    };
    memcpy(ap.ap.ssid, s_ap_ssid, strlen(s_ap_ssid));
    ap.ap.ssid_len = strlen(s_ap_ssid);
    memcpy(ap.ap.password, SETUP_PASSWORD, strlen(SETUP_PASSWORD));

    const esp_timer_create_args_t timers[] = {
        {.callback = retry, .name = "retry"}, {.callback = fallback, .name = "fallback"},
        {.callback = linger, .name = "linger"}, {.callback = apply, .name = "apply"},
    };
    esp_timer_handle_t *handles[] = {&s_retry, &s_fallback, &s_linger, &s_apply};
    for (int i = 0; i < 4; ++i) ESP_ERROR_CHECK(esp_timer_create(&timers[i], handles[i]));

    s_ap_up = !s_ssid[0];
    /* The AP's config is refused in STA mode (ESP_ERR_WIFI_MODE); set_ap later only switches the mode,
       so the config goes in first under APSTA. */
    ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_APSTA));
    ESP_ERROR_CHECK(esp_wifi_set_config(WIFI_IF_AP, &ap));
    ESP_ERROR_CHECK(esp_wifi_set_mode(s_ap_up ? WIFI_MODE_APSTA : WIFI_MODE_STA));
    ESP_ERROR_CHECK(esp_wifi_start());
    /* The C5 joins a 5 GHz network too, which leaves 2.4 GHz to the radio and the console. */
    set_band();
    if (s_force_5g) ESP_LOGI(TAG, "5 GHz only");
    if (s_ap_up) captive_start();
    else esp_timer_start_once(s_fallback, FALLBACK_US);
    if (s_ssid[0]) ESP_LOGI(TAG, "joining %s", s_ssid);
    else ESP_LOGI(TAG, "no network stored: setup access point %s", s_ap_ssid);
}

net_state_t net_state(void)
{
    if (s_online) return NET_ONLINE;
    if (s_ap_up) return NET_SETUP;
    return s_started ? NET_CONNECTING : NET_STARTING;
}

void net_station(char *ssid, size_t ssid_size, char *ip, size_t ip_size, int *rssi, int *channel)
{
    xSemaphoreTake(s_lock, portMAX_DELAY);
    snprintf(ssid, ssid_size, "%s", s_ssid);
    xSemaphoreGive(s_lock);
    *rssi = *channel = 0;
    ip[0] = 0;
    if (!s_online) return;
    snprintf(ip, ip_size, IPSTR, IP2STR(&s_ip));
    wifi_ap_record_t record;
    if (esp_wifi_sta_get_ap_info(&record) == ESP_OK) {
        *rssi = record.rssi;
        *channel = record.primary;
    }
}

bool net_setup_ap(char *ssid, size_t size)
{
    snprintf(ssid, size, "%s", s_ap_ssid);
    return s_ap_up;
}

size_t net_scan_json(char *out, size_t size)
{
    s_scanning = true;
    esp_timer_stop(s_retry);
    if (!s_online) esp_wifi_disconnect();   /* a station still trying refuses to scan */
    const wifi_scan_config_t config = {.show_hidden = false};
    esp_err_t err = esp_wifi_scan_start(&config, true);
    uint16_t count = 24;
    static wifi_ap_record_t records[24];
    if (err == ESP_OK) err = esp_wifi_scan_get_ap_records(&count, records);
    s_scanning = false;
    if (!s_online) connect_station();
    size_t n = 0;
    out[n++] = '[';
    if (err == ESP_OK) {
        for (int i = 0; i < count && n + 96 < size; ++i) {
            const char *ssid = (const char *)records[i].ssid;
            if (!ssid[0]) continue;
            bool seen = false;   /* records come strongest first: keep the first of each name */
            for (int j = 0; j < i && !seen; ++j) seen = !strcmp(ssid, (const char *)records[j].ssid);
            if (seen) continue;
            if (n > 1) out[n++] = ',';
            n += snprintf(out + n, size - n, "{\"ssid\":\"");
            n += json_escape(out + n, size - n, ssid, strlen(ssid));
            n += snprintf(out + n, size - n, "\",\"rssi\":%d,\"channel\":%d,\"secure\":%s}", records[i].rssi,
                          records[i].primary, records[i].authmode == WIFI_AUTH_OPEN ? "false" : "true");
        }
    }
    out[n++] = ']';
    out[n] = 0;
    return n;
}
