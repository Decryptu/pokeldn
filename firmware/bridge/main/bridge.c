/* The radio link: UART1 on the configured TX/RX pins to one TCP host at a time; the newest connection wins, so a host
   that vanished without closing never locks the radio away. Bytes pass unchanged: framing, CRC and
   CREDIT stay between the radio and the host. docs/hardware_esp32.md, The network bridge. */
#include "bridge.h"

#include <errno.h>
#include <stdio.h>
#include <string.h>

#include "driver/gpio.h"
#include "driver/uart.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"
#include "freertos/task.h"
#include "lwip/netdb.h"
#include "lwip/sockets.h"
#include "nvs.h"
#include "nvs_flash.h"

#define UART UART_NUM_1
/* The radio keeps sending while a send() to the host waits on Wi-Fi: 32 KB is 350 ms of a full
   921600-baud line, far longer at the stream's real rate. */
#define UART_RX_RING 32768
#define UART_TX_RING 16384
#define LED_GPIO CONFIG_BRIDGE_LED_GPIO         /* the XIAOs' yellow LED, lit while low */
#define BUTTON_GPIO CONFIG_BRIDGE_BUTTON_GPIO   /* BOOT: held 5 s forgets the network */
/* The S3 keeps the stream on core 1, away from Wi-Fi's interrupts on core 0, as the radio's wire
   does; the single-core C5 runs everything on core 0. */
#define STREAM_CORE (configNUMBER_OF_CORES - 1)
#define MSG_INFO 0x81
#define MSG_LOG 0x83
#define INFO_HEAD 14     /* protocol, station MAC, softAP MAC, chip revision: radio.c send_info */
#define LOG_LINES 24
#define LOG_WIDTH 120

static const char *TAG = "bridge";

bridge_stats_t g_stats;

static QueueHandle_t s_uart_events;
static SemaphoreHandle_t s_send_lock;   /* held around send(); the server takes it to close */
static atomic_int s_host = -1;
static atomic_bool s_send_failed;   /* the stream shut the host down: its end of stream is counted already */
static uint16_t s_port = BRIDGE_DEFAULT_PORT;

static SemaphoreHandle_t s_radio_lock;
static char s_info[160];
static char s_log[LOG_LINES][LOG_WIDTH];
static unsigned s_log_next;

static uint32_t uptime_s(void) { return (uint32_t)(esp_timer_get_time() / 1000000); }

uint16_t bridge_port(void) { return s_port; }

size_t bridge_uart_backlog(void)
{
    size_t n = 0;
    uart_get_buffered_data_len(UART, &n);
    return n;
}

void bridge_set_port(uint16_t port)
{
    nvs_handle_t nvs;
    if (nvs_open("bridge", NVS_READWRITE, &nvs) != ESP_OK) return;
    nvs_set_u16(nvs, "port", port);
    nvs_commit(nvs);
    nvs_close(nvs);
}

static void load_port(void)
{
    nvs_handle_t nvs;
    if (nvs_open("bridge", NVS_READONLY, &nvs) != ESP_OK) return;
    uint16_t port;
    if (nvs_get_u16(nvs, "port", &port) == ESP_OK && port) s_port = port;
    nvs_close(nvs);
}

/* --- What the radio says, read as it passes --- */

static void keep_text(char *out, size_t size, const uint8_t *text, size_t length)
{
    size_t n = 0;
    for (size_t i = 0; i < length && n + 1 < size; ++i)
        out[n++] = text[i] >= 0x20 && text[i] < 0x7f ? (char)text[i] : '?';
    out[n] = 0;
}

/* One COBS frame, delimiter removed: type, payload, CRC32. */
static void radio_frame(const uint8_t *encoded, size_t used)
{
    static uint8_t frame[400];
    size_t read = 0, out = 0;
    while (read < used) {
        const uint8_t code = encoded[read++];
        if (!code || read + code - 1 > used) return;
        for (int i = 1; i < code; ++i) {
            if (out == sizeof(frame)) return;   /* RX_ETH and other bulk frames: not ours to read */
            frame[out++] = encoded[read++];
        }
        if (code != 255 && read < used) {
            if (out == sizeof(frame)) return;
            frame[out++] = 0;
        }
    }
    if (out < 5) return;
    const uint8_t *body = frame + 1;
    const size_t length = out - 5;
    if (frame[0] == MSG_INFO && length > INFO_HEAD) {
        xSemaphoreTake(s_radio_lock, portMAX_DELAY);
        keep_text(s_info, sizeof(s_info), body + INFO_HEAD, length - INFO_HEAD);
        xSemaphoreGive(s_radio_lock);
    } else if (frame[0] == MSG_LOG && length) {
        xSemaphoreTake(s_radio_lock, portMAX_DELAY);
        keep_text(s_log[s_log_next % LOG_LINES], LOG_WIDTH, body, length);
        ++s_log_next;
        xSemaphoreGive(s_radio_lock);
    }
}

static void radio_watch(const uint8_t *bytes, size_t n)
{
    static uint8_t encoded[400];
    static size_t used;
    static bool long_frame;
    for (size_t i = 0; i < n; ++i) {
        if (bytes[i]) {
            if (used < sizeof(encoded)) encoded[used++] = bytes[i]; else long_frame = true;
            continue;
        }
        atomic_fetch_add(&g_stats.radio_frames, 1);
        if (used && !long_frame) radio_frame(encoded, used);
        used = 0;
        long_frame = false;
    }
}

void bridge_radio_info(char *out, size_t size)
{
    xSemaphoreTake(s_radio_lock, portMAX_DELAY);
    snprintf(out, size, "%s", s_info);
    xSemaphoreGive(s_radio_lock);
}

size_t bridge_radio_log_json(char *out, size_t size)
{
    size_t n = 0;
    if (size < 3) return 0;
    out[n++] = '[';
    xSemaphoreTake(s_radio_lock, portMAX_DELAY);
    const unsigned first = s_log_next > LOG_LINES ? s_log_next - LOG_LINES : 0;
    for (unsigned i = first; i < s_log_next && n + 4 < size; ++i) {
        if (i != first) out[n++] = ',';
        out[n++] = '"';
        const char *line = s_log[i % LOG_LINES];
        n += json_escape(out + n, size - n - 2, line, strlen(line));
        out[n++] = '"';
    }
    xSemaphoreGive(s_radio_lock);
    out[n++] = ']';
    out[n] = 0;
    return n;
}

/* --- Radio to host --- */

/* Why the last host went: the status page shows it, so a run that ended needs no serial console. */
static void note_drop(drop_reason_t reason, int error)
{
    atomic_fetch_add(&g_stats.drops[reason], 1);
    atomic_store(&g_stats.last_drop, reason);
    atomic_store(&g_stats.last_drop_errno, error);
    atomic_store(&g_stats.last_drop_s, uptime_s() ? uptime_s() : 1);
}

static void radio_to_host(const uint8_t *bytes, size_t n)
{
    atomic_fetch_add(&g_stats.radio_bytes, n);
    atomic_store(&g_stats.radio_seen_s, uptime_s() ? uptime_s() : 1);
    radio_watch(bytes, n);
    xSemaphoreTake(s_send_lock, portMAX_DELAY);
    const int s = atomic_load(&s_host);
    if (s < 0) {
        atomic_fetch_add(&g_stats.unheard, n);
    } else {
        for (size_t sent = 0; sent < n;) {
            const int r = send(s, bytes + sent, n - sent, 0);
            if (r <= 0) {
                const int error = errno;
                ESP_LOGW(TAG, "send to host failed (errno %d)", error);
                atomic_store(&s_send_failed, true);
                note_drop(error == EAGAIN || error == EWOULDBLOCK ? DROP_SEND_TIMEOUT : DROP_SEND_ERROR, error);
                /* The server sees the shutdown as an end of stream and closes the socket. */
                shutdown(s, SHUT_RDWR);
                break;
            }
            sent += r;
        }
    }
    xSemaphoreGive(s_send_lock);
}

static void uart_task(void *arg)
{
    static uint8_t chunk[2048];
    for (;;) {
        uart_event_t event;
        if (xQueueReceive(s_uart_events, &event, portMAX_DELAY) != pdTRUE) continue;
        switch (event.type) {
        case UART_DATA: {
            size_t buffered = 0;
            uart_get_buffered_data_len(UART, &buffered);
            while (buffered) {
                const int n = uart_read_bytes(UART, chunk, buffered < sizeof(chunk) ? buffered : sizeof(chunk), 0);
                if (n <= 0) break;
                radio_to_host(chunk, n);
                buffered -= n;
            }
            break;
        }
        case UART_FIFO_OVF:
        case UART_BUFFER_FULL:
            atomic_fetch_add(&g_stats.uart_errors, 1);
            uart_flush_input(UART);
            xQueueReset(s_uart_events);
            break;
        case UART_FRAME_ERR:
        case UART_PARITY_ERR:
        case UART_BREAK:
            atomic_fetch_add(&g_stats.uart_errors, 1);
            break;
        default:
            break;
        }
    }
}

/* --- Host to radio --- */

static void close_host(void)
{
    xSemaphoreTake(s_send_lock, portMAX_DELAY);
    const int s = atomic_exchange(&s_host, -1);
    xSemaphoreGive(s_send_lock);
    if (s < 0) return;
    close(s);
    atomic_store(&g_stats.host, false);
    ESP_LOGI(TAG, "host gone");
}

static void tune(int s)
{
    const int on = 1, idle = 5, interval = 2, count = 3;
    setsockopt(s, IPPROTO_TCP, TCP_NODELAY, &on, sizeof(on));
    setsockopt(s, SOL_SOCKET, SO_KEEPALIVE, &on, sizeof(on));
    setsockopt(s, IPPROTO_TCP, TCP_KEEPIDLE, &idle, sizeof(idle));
    setsockopt(s, IPPROTO_TCP, TCP_KEEPINTVL, &interval, sizeof(interval));
    setsockopt(s, IPPROTO_TCP, TCP_KEEPCNT, &count, sizeof(count));
    /* A stalled host must not hold the radio's stream for long: the UART ring fills meanwhile. 500 ms
       dropped a FireRed trade on a busy 2.4 GHz channel; a short Wi-Fi stall now waits it out, and a
       gone host still goes by keepalive. */
    const struct timeval timeout = {.tv_sec = 3, .tv_usec = 0};
    setsockopt(s, SOL_SOCKET, SO_SNDTIMEO, &timeout, sizeof(timeout));
}

static void server_task(void *arg)
{
    const int listener = socket(AF_INET, SOCK_STREAM, IPPROTO_IP);
    const int on = 1;
    setsockopt(listener, SOL_SOCKET, SO_REUSEADDR, &on, sizeof(on));
    const struct sockaddr_in address = {
        .sin_family = AF_INET, .sin_port = htons(s_port), .sin_addr.s_addr = htonl(INADDR_ANY),
    };
    if (bind(listener, (const struct sockaddr *)&address, sizeof(address)) || listen(listener, 2)) {
        ESP_LOGE(TAG, "cannot listen on port %u", s_port);
        vTaskDelete(NULL);
    }
    ESP_LOGI(TAG, "listening on port %u", s_port);
    static uint8_t chunk[1460];
    for (;;) {
        fd_set readable;
        FD_ZERO(&readable);
        FD_SET(listener, &readable);
        const int host = atomic_load(&s_host);
        if (host >= 0) FD_SET(host, &readable);
        const int top = host > listener ? host : listener;
        if (select(top + 1, &readable, NULL, NULL, NULL) <= 0) continue;
        if (FD_ISSET(listener, &readable)) {
            struct sockaddr_in from;
            socklen_t from_len = sizeof(from);
            const int s = accept(listener, (struct sockaddr *)&from, &from_len);
            if (s >= 0) {
                if (atomic_load(&s_host) >= 0) note_drop(DROP_REPLACED, 0);
                close_host();
                tune(s);
                atomic_store(&g_stats.host_ip, from.sin_addr.s_addr);
                atomic_store(&g_stats.host_since_s, uptime_s());
                atomic_fetch_add(&g_stats.sessions, 1);
                atomic_store(&s_send_failed, false);
                atomic_store(&s_host, s);
                atomic_store(&g_stats.host, true);
                ESP_LOGI(TAG, "host %s connected", inet_ntoa(from.sin_addr));
            }
            continue;
        }
        if (host >= 0 && FD_ISSET(host, &readable)) {
            const int n = recv(host, chunk, sizeof(chunk), 0);
            if (n <= 0) {
                /* After the stream's own shutdown the end of stream is already counted. */
                if (!atomic_exchange(&s_send_failed, false)) {
                    const int error = n < 0 ? errno : 0;
                    note_drop(n == 0 ? DROP_CLOSED : error == ETIMEDOUT ? DROP_KEEPALIVE : DROP_RESET, error);
                }
                close_host();
                continue;
            }
            atomic_fetch_add(&g_stats.host_bytes, n);
            uart_write_bytes(UART, chunk, n);
        }
    }
}

/* --- LED and BOOT button --- */

static void led_task(void *arg)
{
#if LED_GPIO >= 0
    gpio_reset_pin(LED_GPIO);
    gpio_set_direction(LED_GPIO, GPIO_MODE_OUTPUT);
#endif
#if BUTTON_GPIO >= 0
    gpio_config_t button = {
        .pin_bit_mask = 1ULL << BUTTON_GPIO, .mode = GPIO_MODE_INPUT, .pull_up_en = GPIO_PULLUP_ENABLE,
    };
    gpio_config(&button);
#endif
    pixels_start();
    unsigned tick = 0, held = 0, traffic = 0;
    for (;;) {
        ++tick;   /* every 50 ms */
#if BUTTON_GPIO >= 0
        const unsigned was = held;
        held = gpio_get_level(BUTTON_GPIO) ? 0 : held + 1;
        if (!held && was && was < 20) pixels_show_battery();   /* a short press, under 1 s */
#endif
        if (held == 100) {
            ESP_LOGW(TAG, "BOOT held: forgetting the network");
            net_configure("", "");
        }
        bool lit;
        const unsigned bytes = atomic_load(&g_stats.radio_bytes) + atomic_load(&g_stats.host_bytes);
        switch (net_state()) {
        case NET_SETUP: lit = tick % 20 < 10; break;             /* slow blink: setup access point */
        case NET_CONNECTING: lit = tick % 4 < 2; break;          /* fast blink: joining */
        default:
            if (atomic_load(&g_stats.host)) lit = bytes == traffic || tick % 2;   /* on, flickers with traffic */
            else lit = tick % 40 == 0;                           /* a blip: online, waiting for a host */
            break;
        }
        traffic = bytes;
        pixels_tick(tick, held);
#if LED_GPIO >= 0
#if CONFIG_BRIDGE_LED_ACTIVE_LOW
        gpio_set_level(LED_GPIO, !lit);
#else
        gpio_set_level(LED_GPIO, lit);
#endif
#else
        (void)lit;
#endif
        vTaskDelay(pdMS_TO_TICKS(50));
    }
}

void app_main(void)
{
    esp_err_t err = nvs_flash_init();
    if (err == ESP_ERR_NVS_NO_FREE_PAGES || err == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        ESP_ERROR_CHECK(nvs_flash_erase());
        err = nvs_flash_init();
    }
    ESP_ERROR_CHECK(err);
    load_port();
    s_send_lock = xSemaphoreCreateMutex();
    s_radio_lock = xSemaphoreCreateMutex();

    const uart_config_t config = {
        .baud_rate = BRIDGE_BAUD,
        .data_bits = UART_DATA_8_BITS,
        .parity = UART_PARITY_DISABLE,
        .stop_bits = UART_STOP_BITS_1,
        .flow_ctrl = UART_HW_FLOWCTRL_DISABLE,
        .source_clk = UART_SCLK_DEFAULT,
    };
    ESP_ERROR_CHECK(uart_driver_install(UART, UART_RX_RING, UART_TX_RING, 64, &s_uart_events, 0));
    ESP_ERROR_CHECK(uart_param_config(UART, &config));
    ESP_ERROR_CHECK(uart_set_pin(UART, BRIDGE_UART_TX, BRIDGE_UART_RX, UART_PIN_NO_CHANGE, UART_PIN_NO_CHANGE));
    ESP_ERROR_CHECK(uart_set_rx_full_threshold(UART, 64));

    net_start();
    web_start();
    battery_start();
    xTaskCreatePinnedToCore(uart_task, "radio_rx", 4096, NULL, 20, NULL, STREAM_CORE);
    xTaskCreatePinnedToCore(server_task, "host_rx", 4096, NULL, 19, NULL, STREAM_CORE);
    xTaskCreate(led_task, "led", 3072, NULL, 2, NULL);
}
