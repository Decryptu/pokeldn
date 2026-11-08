/* Two WS2812 status pixels on one data pin, chained: the first shows the network, the second the link
   to the host and the radio. RMT sends the frames, so the stream never waits on them.
   docs/hardware_esp32.md, The network bridge. */
#include "bridge.h"

#include <string.h>

#include "driver/rmt_tx.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "nvs.h"

#define PIXEL_GPIO CONFIG_BRIDGE_PIXEL_GPIO
#define TICKS_PER_S 20   /* the LED task's 50 ms */
#define WEAK_RSSI -75
#define RADIO_QUIET_S 10   /* a connected host hears the radio well within this */
#define BACKLOG_WARN 4096
#define BACKLOG_BAD 16384

static const char *TAG = "pixels";

typedef struct { uint8_t r, g, b; } rgb_t;

static const rgb_t OFF = {0, 0, 0}, WHITE = {255, 255, 255}, GREEN = {0, 255, 40}, YELLOW = {255, 150, 0},
                   BLUE = {0, 60, 255}, CYAN = {0, 180, 255}, ORANGE = {255, 60, 0}, RED = {255, 0, 0},
                   PURPLE = {170, 0, 255}, MAGENTA = {255, 0, 160};

static rmt_channel_handle_t s_channel;
static esp_err_t s_error;   /* the last frame's, for the log */
static uint8_t s_frame[6];
static rmt_encoder_handle_t s_encoder;
static uint8_t s_percent = CONFIG_BRIDGE_PIXEL_BRIGHTNESS;
static volatile unsigned s_identify, s_restarting, s_battery;   /* ticks left */

bool pixels_present(void) { return s_channel != NULL; }

uint8_t pixels_brightness(void) { return s_percent; }

void pixels_set_brightness(uint8_t percent)
{
    s_percent = percent > 100 ? 100 : percent;
    nvs_handle_t nvs;
    if (nvs_open("pixels", NVS_READWRITE, &nvs) != ESP_OK) return;
    nvs_set_u8(nvs, "percent", s_percent);
    nvs_commit(nvs);
    nvs_close(nvs);
}

void pixels_identify(void) { s_identify = 5 * TICKS_PER_S; }

void pixels_restarting(void) { s_restarting = TICKS_PER_S; }

void pixels_show_battery(void) { s_battery = 3 * TICKS_PER_S; }

void pixels_start(void)
{
#if PIXEL_GPIO >= 0
    s_battery = 3 * TICKS_PER_S;   /* the charge once at start, when a cell is there */
    nvs_handle_t nvs;
    if (nvs_open("pixels", NVS_READONLY, &nvs) == ESP_OK) {
        nvs_get_u8(nvs, "percent", &s_percent);
        nvs_close(nvs);
    }
    const rmt_tx_channel_config_t channel = {
        .gpio_num = PIXEL_GPIO, .clk_src = RMT_CLK_SRC_DEFAULT, .resolution_hz = 10000000,
        /* Two blocks: the frame's 48 bits and its end in one go, with no refill a busy Wi-Fi
           interrupt could delay into a broken bit. */
        .mem_block_symbols = 96, .trans_queue_depth = 2,
    };
    /* WS2812 bits at 0.1 us a tick: 0 is 0.4 us high and 0.8 us low, 1 the other way round. The line
       idles low between frames, far past the 280 us reset. */
    const rmt_bytes_encoder_config_t bits = {
        .bit0 = {.level0 = 1, .duration0 = 4, .level1 = 0, .duration1 = 8},
        .bit1 = {.level0 = 1, .duration0 = 8, .level1 = 0, .duration1 = 4},
        .flags.msb_first = 1,
    };
    if (rmt_new_tx_channel(&channel, &s_channel) != ESP_OK || rmt_new_bytes_encoder(&bits, &s_encoder) != ESP_OK ||
        rmt_enable(s_channel) != ESP_OK) {
        ESP_LOGW(TAG, "no RMT channel for GPIO%d", PIXEL_GPIO);
        s_channel = NULL;
    }
#else
    ESP_LOGI(TAG, "none configured");
#endif
}

static rgb_t scale(rgb_t c, unsigned of255)
{
    return (rgb_t){c.r * of255 / 255, c.g * of255 / 255, c.b * of255 / 255};
}

/* 0..255 and back once a period, for a pulse. */
static unsigned wave(unsigned tick, unsigned period)
{
    const unsigned t = tick % period * 510 / period;
    return t < 256 ? t : 510 - t;
}

static void show(rgb_t net, rgb_t link, unsigned percent)
{
    static uint8_t last[6] = {1};
    /* Perceived brightness grows with the square of the drive. */
    const unsigned level = percent ? (percent * percent * 255 / 10000 ?: 1) : 0;
    net = scale(net, level);
    link = scale(link, level);
    const uint8_t frame[6] = {net.g, net.r, net.b, link.g, link.r, link.b};   /* GRB, first pixel first */
    /* Unchanged, once a second still: pixels that got power later, or lost it a moment, catch up. */
    static unsigned calls;
    if (!memcmp(frame, last, sizeof(frame)) && ++calls % TICKS_PER_S) return;
    memcpy(last, frame, sizeof(frame));
    const rmt_transmit_config_t once = {.loop_count = 0};
    memcpy(s_frame, frame, sizeof(frame));
    s_error = rmt_transmit(s_channel, s_encoder, frame, sizeof(frame), &once);
    if (s_error == ESP_OK) s_error = rmt_tx_wait_all_done(s_channel, 20);
}

static rgb_t network(unsigned tick)
{
    static int rssi, channel;
    if (tick % TICKS_PER_S == 1) {
        char ssid[33], ip[16];
        net_station(ssid, sizeof(ssid), ip, sizeof(ip), &rssi, &channel);
    }
    switch (net_state()) {
    case NET_SETUP: return tick % TICKS_PER_S < TICKS_PER_S / 2 ? BLUE : OFF;   /* setup access point open */
    case NET_CONNECTING: return scale(WHITE, 20 + wave(tick, TICKS_PER_S) * 235 / 255);
    case NET_ONLINE: {
        /* 2.4 GHz shares the air with the radio and the console: it works, but slower. */
        const rgb_t band = channel > 14 ? GREEN : YELLOW;
        /* A weak signal: a short gap every 2 s. */
        if (rssi && rssi < WEAK_RSSI && tick % (2 * TICKS_PER_S) < 2) return OFF;
        /* Charging: breathes until full. */
        const battery_t cell = battery_read();
        if (cell.charging && cell.percent < 100) return scale(band, 50 + wave(tick, 3 * TICKS_PER_S) * 205 / 255);
        return band;
    }
    default: return scale(WHITE, 40);
    }
}

static rgb_t link(unsigned tick)
{
    static unsigned traffic, bad_sends, bad_hosts, line_errors, flash;
    static rgb_t flash_color;
    const unsigned sends = atomic_load(&g_stats.drops[DROP_SEND_TIMEOUT]) + atomic_load(&g_stats.drops[DROP_SEND_ERROR]);
    const unsigned hosts = atomic_load(&g_stats.drops[DROP_KEEPALIVE]) + atomic_load(&g_stats.drops[DROP_RESET]);
    const unsigned errors = atomic_load(&g_stats.uart_errors);
    /* A host that closes the connection or is replaced by a newer one went as it should; these did not. */
    if (sends != bad_sends) { flash = 3 * TICKS_PER_S; flash_color = ORANGE; }
    else if (hosts != bad_hosts) { flash = 3 * TICKS_PER_S; flash_color = RED; }
    else if (errors != line_errors && !flash) { flash = TICKS_PER_S / 4; flash_color = RED; }
    bad_sends = sends, bad_hosts = hosts, line_errors = errors;
    const unsigned bytes = atomic_load(&g_stats.radio_bytes) + atomic_load(&g_stats.host_bytes);
    const bool moved = bytes != traffic;
    traffic = bytes;

    if (flash) return --flash % (TICKS_PER_S / 4) < TICKS_PER_S / 8 ? flash_color : OFF;
    if (!atomic_load(&g_stats.host)) return OFF;
    const uint32_t seen = atomic_load(&g_stats.radio_seen_s), now = (uint32_t)(esp_timer_get_time() / 1000000);
    if (!seen || now - seen > RADIO_QUIET_S) return PURPLE;   /* the host is here, the radio is not */
    const size_t backlog = bridge_uart_backlog();
    if (backlog > BACKLOG_BAD) return RED;   /* Wi-Fi does not keep up with the radio */
    if (backlog > BACKLOG_WARN) return YELLOW;
    return scale(CYAN, moved ? 255 : 70);   /* flickers with traffic */
}

/* Red through yellow at half to green at full. */
static rgb_t charge(unsigned percent)
{
    if (percent < 50) return (rgb_t){255, percent * 150 / 50, 0};
    return (rgb_t){255 * (100 - percent) / 50, 150 + (percent - 50) * 105 / 50, 0};
}

void pixels_tick(unsigned tick, unsigned held)
{
    if (tick == 5 * TICKS_PER_S) {
        /* Once, after USB Serial/JTAG is back from the reset: the start's own lines are lost. */
        const battery_t cell = battery_read();
        ESP_LOGI(TAG, "GPIO%d %s at %u %%, last frame GRB %02x%02x%02x %02x%02x%02x (%s); battery %u mV %u %%%s%s",
                 PIXEL_GPIO, s_channel ? "ready" : "not started", s_percent, s_frame[0], s_frame[1], s_frame[2],
                 s_frame[3], s_frame[4], s_frame[5], esp_err_to_name(s_error), cell.mv, cell.percent,
                 cell.present ? "" : " (none)", cell.charging ? " charging" : "");
    }
    if (!s_channel) return;
    rgb_t net = network(tick), lnk = link(tick);
    unsigned percent = s_percent;
    const battery_t cell = battery_read();
    if (cell.present && !cell.charging && cell.percent < 15) {
        /* Low: a red blip every 4 s on the network pixel, a blink each second under 5 %. */
        if (cell.percent < 5 ? tick % TICKS_PER_S < TICKS_PER_S / 2 : tick % (4 * TICKS_PER_S) < 3) net = RED;
    }
    if (s_battery) --s_battery;
    if (held > 20) {
        /* BOOT past a short press: both fill red until the network is forgotten at 5 s. */
        const unsigned from = 20, half = 40;
        net = scale(RED, held >= from + half ? 255 : (held - from) * 255 / half);
        lnk = held > from + half ? scale(RED, held >= from + 2 * half ? 255 : (held - from - half) * 255 / half) : OFF;
    } else if (s_restarting) {
        --s_restarting;
        net = lnk = WHITE;
    } else if (s_identify) {
        --s_identify;
        const bool phase = tick % (TICKS_PER_S / 2) < TICKS_PER_S / 4;
        net = phase ? MAGENTA : WHITE;
        lnk = phase ? WHITE : MAGENTA;
        if (percent < 60) percent = 60;   /* found even with the pixels turned off */
    } else if (s_battery && cell.present) {
        /* Both in the charge's colour, pulsing while it charges. */
        net = lnk = cell.charging ? scale(charge(cell.percent), 40 + wave(tick, TICKS_PER_S) * 215 / 255)
                                  : charge(cell.percent);
        if (percent < 30) percent = 30;
    }
    show(net, lnk, percent);
}
