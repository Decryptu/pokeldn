/* The setup and monitoring page on port 80, and its JSON API:
     GET  /api/status   network, host, radio and counters
     GET  /api/scan     networks in range
     POST /api/wifi     ssid=...&password=... (form encoded); an empty ssid forgets the network
     POST /api/port     port=N, after a restart
     POST /api/restart
     POST /api/band     force5g=1|0, restarts
     POST /api/pixels   brightness=0..100 (percent) for the status pixels
     POST /api/identify both pixels blink for 5 s
   Any other path serves the page, which is what a captive portal check expects. */
#include "bridge.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "esp_app_desc.h"
#include "esp_http_server.h"
#include "esp_log.h"
#include "esp_system.h"
#include "esp_timer.h"
#include "esp_wifi.h"
#include "lwip/inet.h"

extern const char index_html_start[] asm("_binary_index_html_start");
extern const char index_html_end[] asm("_binary_index_html_end");

static const char *TAG = "web";

size_t json_escape(char *out, size_t size, const char *text, size_t length)
{
    size_t n = 0;
    for (size_t i = 0; i < length && n + 7 < size; ++i) {
        const unsigned char c = text[i];
        if (c == '"' || c == '\\') { out[n++] = '\\'; out[n++] = c; }
        else if (c < 0x20) n += snprintf(out + n, size - n, "\\u%04x", c);
        else out[n++] = c;
    }
    out[n] = 0;
    return n;
}

static esp_err_t page(httpd_req_t *req)
{
    httpd_resp_set_type(req, "text/html; charset=utf-8");
    httpd_resp_set_hdr(req, "Cache-Control", "no-store");
    return httpd_resp_send(req, index_html_start, index_html_end - index_html_start - 1);
}

static esp_err_t send_json(httpd_req_t *req, const char *json, size_t length)
{
    httpd_resp_set_type(req, "application/json");
    httpd_resp_set_hdr(req, "Cache-Control", "no-store");
    return httpd_resp_send(req, json, length);
}

static esp_err_t status(httpd_req_t *req)
{
    static char json[4096];
    char ssid[33], ip[16], ap_ssid[33], host_ip[16], text[160], escaped[200];
    int rssi, channel;
    net_station(ssid, sizeof(ssid), ip, sizeof(ip), &rssi, &channel);
    const bool ap_up = net_setup_ap(ap_ssid, sizeof(ap_ssid));
    static const char *const STATES[] = {"starting", "connecting", "online", "setup"};
    const struct in_addr host = {.s_addr = atomic_load(&g_stats.host_ip)};
    inet_ntoa_r(host, host_ip, sizeof(host_ip));
    const uint32_t now = (uint32_t)(esp_timer_get_time() / 1000000);
    const uint32_t seen = atomic_load(&g_stats.radio_seen_s);
    const battery_t cell = battery_read();

    size_t n = snprintf(json, sizeof(json),
        "{\"version\":\"%s\",\"uptime\":%lu,\"heap\":%lu,\"heap_min\":%lu,"
        "\"net\":{\"state\":\"%s\",\"ssid\":\"",
        esp_app_get_description()->version, (unsigned long)now,
        (unsigned long)esp_get_free_heap_size(), (unsigned long)esp_get_minimum_free_heap_size(),
        STATES[net_state()]);
    n += json_escape(json + n, sizeof(json) - n, ssid, strlen(ssid));
    n += snprintf(json + n, sizeof(json) - n,
        "\",\"ip\":\"%s\",\"rssi\":%d,\"channel\":%d,\"ap\":%s,\"ap_ssid\":\"%s\","
        "\"can_5g\":%s,\"force_5g\":%s},"
        "\"target\":\"%s\",\"port\":%u,\"baud\":%u,\"pixels\":{\"present\":%s,\"brightness\":%u},"
        "\"battery\":{\"present\":%s,\"mv\":%u,\"percent\":%u,\"charging\":%s},"
        "\"host\":{\"connected\":%s,\"ip\":\"%s\",\"since\":%lu,\"sessions\":%u,",
        ip, rssi, channel, ap_up ? "true" : "false", ap_ssid, net_can_5g() ? "true" : "false",
        net_force_5g() ? "true" : "false", CONFIG_IDF_TARGET, bridge_port(), BRIDGE_BAUD,
        pixels_present() ? "true" : "false", pixels_brightness(),
        cell.present ? "true" : "false", cell.mv, cell.percent, cell.charging ? "true" : "false",
        atomic_load(&g_stats.host) ? "true" : "false", host_ip,
        (unsigned long)(now - atomic_load(&g_stats.host_since_s)), atomic_load(&g_stats.sessions));
    /* Why hosts went, by reason (bridge.h drop_reason_t), and the last one. */
    static const char *const DROPS[] = {"none", "send_timeout", "send_error", "closed", "keepalive", "reset",
                                        "replaced"};
    n += snprintf(json + n, sizeof(json) - n, "\"drops\":{");
    for (int i = DROP_SEND_TIMEOUT; i < DROP_REASONS; ++i)
        n += snprintf(json + n, sizeof(json) - n, "%s\"%s\":%u", i == DROP_SEND_TIMEOUT ? "" : ",", DROPS[i],
                      atomic_load(&g_stats.drops[i]));
    const uint32_t dropped = atomic_load(&g_stats.last_drop_s);
    n += snprintf(json + n, sizeof(json) - n, "},\"last_drop\":{\"reason\":\"%s\",\"errno\":%d,\"ago\":%ld}},",
                  DROPS[atomic_load(&g_stats.last_drop)], atomic_load(&g_stats.last_drop_errno),
                  dropped ? (long)(now - dropped) : -1L);
    bridge_radio_info(text, sizeof(text));
    json_escape(escaped, sizeof(escaped), text, strlen(text));
    n += snprintf(json + n, sizeof(json) - n,
        "\"radio\":{\"info\":\"%s\",\"quiet\":%ld,\"bytes\":%u,\"frames\":%u,\"unheard\":%u,"
        "\"errors\":%u,\"host_bytes\":%u,\"log\":",
        escaped, seen ? (long)(now - seen) : -1L, atomic_load(&g_stats.radio_bytes),
        atomic_load(&g_stats.radio_frames), atomic_load(&g_stats.unheard),
        atomic_load(&g_stats.uart_errors), atomic_load(&g_stats.host_bytes));
    n += bridge_radio_log_json(json + n, sizeof(json) - n - 3);
    n += snprintf(json + n, sizeof(json) - n, "}}");
    return send_json(req, json, n);
}

static esp_err_t scan(httpd_req_t *req)
{
    static char json[3072];
    const size_t n = net_scan_json(json, sizeof(json));
    return send_json(req, json, n);
}

/* A form field, percent-decoded. */
static bool field(const char *body, const char *name, char *out, size_t size)
{
    const size_t name_len = strlen(name);
    for (const char *p = body; p && *p; p = strchr(p, '&') ? strchr(p, '&') + 1 : NULL) {
        if (strncmp(p, name, name_len) || p[name_len] != '=') continue;
        size_t n = 0;
        for (const char *v = p + name_len + 1; *v && *v != '&' && n + 1 < size; ++v) {
            if (*v == '+') out[n++] = ' ';
            else if (*v == '%' && v[1] && v[2]) {
                const char hex[3] = {v[1], v[2], 0};
                out[n++] = (char)strtol(hex, NULL, 16);
                v += 2;
            } else out[n++] = *v;
        }
        out[n] = 0;
        return true;
    }
    return false;
}

static int read_body(httpd_req_t *req, char *body, size_t size)
{
    if (req->content_len >= size) return -1;
    size_t got = 0;
    while (got < req->content_len) {
        const int r = httpd_req_recv(req, body + got, req->content_len - got);
        if (r <= 0) return -1;
        got += r;
    }
    body[got] = 0;
    return got;
}

static esp_err_t wifi(httpd_req_t *req)
{
    char body[256], ssid[33] = "", password[65] = "";
    if (read_body(req, body, sizeof(body)) < 0 || !field(body, "ssid", ssid, sizeof(ssid)))
        return httpd_resp_send_err(req, HTTPD_400_BAD_REQUEST, "ssid missing");
    field(body, "password", password, sizeof(password));
    if (password[0] && strlen(password) < 8)
        return httpd_resp_send_err(req, HTTPD_400_BAD_REQUEST, "a WPA password has 8 characters or more");
    ESP_LOGI(TAG, "network set to '%s'", ssid);
    net_configure(ssid, password);
    return send_json(req, "{\"ok\":true}", 11);
}

static esp_err_t port(httpd_req_t *req)
{
    char body[64], value[8];
    if (read_body(req, body, sizeof(body)) < 0 || !field(body, "port", value, sizeof(value)))
        return httpd_resp_send_err(req, HTTPD_400_BAD_REQUEST, "port missing");
    const long port = strtol(value, NULL, 10);
    if (port < 1 || port > 65535 || port == 80 || port == 53)
        return httpd_resp_send_err(req, HTTPD_400_BAD_REQUEST, "port must be 1..65535, not 53 or 80");
    bridge_set_port((uint16_t)port);
    return send_json(req, "{\"ok\":true}", 11);
}

static void restart_later(void *arg) { esp_restart(); }

/* Half a second later, so the page gets its answer first. */
static void restart_soon(void)
{
    static esp_timer_handle_t timer;
    const esp_timer_create_args_t args = {.callback = restart_later, .name = "restart"};
    if (!timer) esp_timer_create(&args, &timer);
    esp_timer_start_once(timer, 500000);
    pixels_restarting();
}

static esp_err_t restart(httpd_req_t *req)
{
    restart_soon();
    return send_json(req, "{\"ok\":true}", 11);
}

/* force5g=1 holds the station to 5 GHz, 0 lets it pick; the bridge restarts to apply it. */
static esp_err_t band(httpd_req_t *req)
{
    char body[64], value[4];
    if (read_body(req, body, sizeof(body)) < 0 || !field(body, "force5g", value, sizeof(value)))
        return httpd_resp_send_err(req, HTTPD_400_BAD_REQUEST, "force5g missing");
    if (!net_can_5g()) return httpd_resp_send_err(req, HTTPD_400_BAD_REQUEST, "this chip has no 5 GHz");
    net_set_force_5g(value[0] == '1');
    ESP_LOGI(TAG, "5 GHz only %s; restarting", value[0] == '1' ? "on" : "off");
    restart_soon();
    return send_json(req, "{\"ok\":true}", 11);
}

/* brightness=0..100 percent for the status pixels, stored and shown at once. */
static esp_err_t pixels(httpd_req_t *req)
{
    char body[64], value[8];
    if (read_body(req, body, sizeof(body)) < 0 || !field(body, "brightness", value, sizeof(value)))
        return httpd_resp_send_err(req, HTTPD_400_BAD_REQUEST, "brightness missing");
    const long percent = strtol(value, NULL, 10);
    if (percent < 0 || percent > 100) return httpd_resp_send_err(req, HTTPD_400_BAD_REQUEST, "brightness is 0..100");
    pixels_set_brightness((uint8_t)percent);
    return send_json(req, "{\"ok\":true}", 11);
}

static esp_err_t identify(httpd_req_t *req)
{
    pixels_identify();
    return send_json(req, "{\"ok\":true}", 11);
}

void web_start(void)
{
    httpd_config_t config = HTTPD_DEFAULT_CONFIG();
    config.uri_match_fn = httpd_uri_match_wildcard;
    config.stack_size = 8192;
    config.lru_purge_enable = true;
    config.max_uri_handlers = 12;
    config.core_id = 0;
    httpd_handle_t server;
    if (httpd_start(&server, &config) != ESP_OK) {
        ESP_LOGE(TAG, "cannot start the web server");
        return;
    }
    const httpd_uri_t routes[] = {
        {.uri = "/api/status", .method = HTTP_GET, .handler = status},
        {.uri = "/api/scan", .method = HTTP_GET, .handler = scan},
        {.uri = "/api/wifi", .method = HTTP_POST, .handler = wifi},
        {.uri = "/api/port", .method = HTTP_POST, .handler = port},
        {.uri = "/api/restart", .method = HTTP_POST, .handler = restart},
        {.uri = "/api/band", .method = HTTP_POST, .handler = band},
        {.uri = "/api/pixels", .method = HTTP_POST, .handler = pixels},
        {.uri = "/api/identify", .method = HTTP_POST, .handler = identify},
        {.uri = "/*", .method = HTTP_GET, .handler = page},
    };
    for (size_t i = 0; i < sizeof(routes) / sizeof(routes[0]); ++i) httpd_register_uri_handler(server, &routes[i]);
}
