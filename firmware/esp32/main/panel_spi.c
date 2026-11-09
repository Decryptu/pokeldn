/* A colour SPI panel (ST7796S or ST7789) that draws the 128x64 frame at a whole scale in the middle, in
   screen.h's two colours, with the backlight on LEDC PWM for the dim step. One driver for every colour
   board: POKELDN_DISPLAY picks the board's numbers below. docs/hardware_esp32.md, The screen. */
#include <string.h>

#include "driver/gpio.h"
#include "driver/ledc.h"
#include "driver/spi_master.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

#include "panel.h"
#include "scene.h"
#include "screen.h"

#if defined(POKELDN_DISPLAY_E32R40T)
/* 480x320 ST7796S [lcdwiki.com 4.0inch_ESP32-32E_Display]. GPIO2 is the classic board's LED pin: led.c
   uses the blue RGB LED here. */
#define LCD_HOST SPI2_HOST
#define LCD_CS 15
#define LCD_DC 2
#define LCD_SCK 14
#define LCD_MOSI 13
#define LCD_MODE 0
#define LCD_BACKLIGHT 27
#define BACKLIGHT_INVERT 0      /* lit while high */
#define LCD_W 480
#define LCD_H 320
#define SCALE 3
#define MADCTL 0x28             /* landscape: MV, BGR */
#elif defined(POKELDN_DISPLAY_SZPI)
/* 320x240 ST7789 [xiaozhi-esp32 boards/lckfb/szpi-esp32s3]. CS is the PCA9557's bit 0, held low by
   board_szpi.c. Mode 0 leaves this panel black; a constant backlight level never lights it. */
#include "board_szpi.h"
#define LCD_HOST SPI3_HOST
#define LCD_CS -1
#define LCD_DC 39
#define LCD_SCK 41
#define LCD_MOSI 40
#define LCD_MODE 2
#define LCD_BACKLIGHT 42
#define BACKLIGHT_INVERT 1      /* lit while low */
#define LCD_W 320
#define LCD_H 240
#define SCALE 2
#define MADCTL 0x60             /* swap_xy (MV) and mirror_x (MX), RGB */
#else
#error "panel_spi.c needs POKELDN_DISPLAY=E32R40T or SZPI"
#endif

#define LEFT ((LCD_W - SCREEN_W * SCALE) / 2)
#define TOP ((LCD_H - SCREEN_H * SCALE) / 2)
#define RGB565(c) ((uint16_t)(((c) >> 8 & 0xf800) | ((c) >> 5 & 0x07e0) | ((c) >> 3 & 0x001f)))
/* The panel reads each pixel high byte first. */
#define WIRE(c) ((uint16_t)(RGB565(c) >> 8 | RGB565(c) << 8))
#define LIT WIRE(SCREEN_LIT_RGB)
#define DARK WIRE(SCREEN_DARK_RGB)
#define DUTY_MAX 8191           /* 13 bits at 5 kHz */
/* By enum scene_power. Full on stays below 100 %: a boost converter that wants a switching signal
   goes dark on a constant level. */
static const uint32_t BACKLIGHT[] = {DUTY_MAX * 95 / 100, DUTY_MAX * 12 / 100, 0};

static spi_device_handle_t s_spi;
static uint16_t s_rows[SCREEN_W * SCALE * SCALE];   /* one frame row, SCALE panel rows */
static uint8_t s_shown[SCREEN_BYTES];
static bool s_any_shown;

static void select_panel(bool on)
{
    if (LCD_CS >= 0) gpio_set_level(LCD_CS, !on);
}

static bool send(const void *data, size_t length)
{
    spi_transaction_t t = {.length = length * 8, .tx_buffer = data};
    return spi_device_transmit(s_spi, &t) == ESP_OK;
}

static bool command(uint8_t op, const uint8_t *args, size_t length)
{
    gpio_set_level(LCD_DC, 0);
    if (!send(&op, 1)) return false;
    gpio_set_level(LCD_DC, 1);
    return !length || send(args, length);
}

/* CS is held across a command and its data: one transaction each, the controller latches DC per byte. */
static bool window(int x, int y, int w, int h)
{
    const uint8_t cols[] = {x >> 8, x & 0xff, (x + w - 1) >> 8, (x + w - 1) & 0xff};
    const uint8_t rows[] = {y >> 8, y & 0xff, (y + h - 1) >> 8, (y + h - 1) & 0xff};
    return command(0x2a, cols, 4) && command(0x2b, rows, 4) && command(0x2c, NULL, 0);
}

static bool backlight_start(void)
{
    const ledc_timer_config_t timer = {
        .speed_mode = LEDC_LOW_SPEED_MODE, .duty_resolution = LEDC_TIMER_13_BIT,
        .timer_num = LEDC_TIMER_1, .freq_hz = 5000, .clk_cfg = LEDC_AUTO_CLK,
    };
    const ledc_channel_config_t channel = {
        .gpio_num = LCD_BACKLIGHT, .speed_mode = LEDC_LOW_SPEED_MODE, .channel = LEDC_CHANNEL_1,
        .timer_sel = LEDC_TIMER_1, .duty = 0, .hpoint = 0, .flags.output_invert = BACKLIGHT_INVERT,
    };
    return ledc_timer_config(&timer) == ESP_OK && ledc_channel_config(&channel) == ESP_OK;
}

bool panel_power(uint8_t power)
{
    return ledc_set_duty(LEDC_LOW_SPEED_MODE, LEDC_CHANNEL_1, BACKLIGHT[power]) == ESP_OK &&
           ledc_update_duty(LEDC_LOW_SPEED_MODE, LEDC_CHANNEL_1) == ESP_OK;
}

bool panel_init(void)
{
#if defined(POKELDN_DISPLAY_SZPI)
    if (!board_szpi_start()) return false;
#endif
    const gpio_config_t io = {
        .pin_bit_mask = (LCD_CS >= 0 ? 1ULL << LCD_CS : 0) | 1ULL << LCD_DC, .mode = GPIO_MODE_OUTPUT,
    };
    if (gpio_config(&io) != ESP_OK || !backlight_start()) return false;
    select_panel(false);
    const spi_bus_config_t bus = {
        .mosi_io_num = LCD_MOSI, .miso_io_num = -1, .sclk_io_num = LCD_SCK,
        .quadwp_io_num = -1, .quadhd_io_num = -1, .max_transfer_sz = sizeof(s_rows),
    };
    const spi_device_interface_config_t device = {
        .clock_speed_hz = 40000000, .mode = LCD_MODE, .spics_io_num = -1, .queue_size = 1,
    };
    if (spi_bus_initialize(LCD_HOST, &bus, SPI_DMA_CH_AUTO) != ESP_OK ||
        spi_bus_add_device(LCD_HOST, &device, &s_spi) != ESP_OK) return false;

    select_panel(true);
    const uint8_t rgb565 = 0x55, madctl = MADCTL;
    bool ok = command(0x01, NULL, 0);                     /* software reset */
    vTaskDelay(pdMS_TO_TICKS(150));
    ok = ok && command(0x11, NULL, 0);                    /* sleep out */
    vTaskDelay(pdMS_TO_TICKS(120));
    ok = ok && command(0x3a, &rgb565, 1) && command(0x36, &madctl, 1) &&
         command(0x21, NULL, 0) && window(0, 0, LCD_W, LCD_H);   /* 0x21: these IPS modules need inversion */
    for (int i = 0; i < SCREEN_W * SCALE * SCALE; ++i) s_rows[i] = DARK;
    for (size_t left = LCD_W * LCD_H; ok && left; ) {
        const size_t n = left < SCREEN_W * SCALE * SCALE ? left : SCREEN_W * SCALE * SCALE;
        ok = send(s_rows, n * 2);
        left -= n;
    }
    ok = ok && command(0x29, NULL, 0);                    /* display on */
    select_panel(false);
    return ok && panel_power(SCENE_ON);
}

/* Up to 150 KB a frame over SPI: an unchanged frame is not sent again. */
void panel_present(const uint8_t *frame)
{
    if (s_any_shown && !memcmp(frame, s_shown, SCREEN_BYTES)) return;
    select_panel(true);
    bool ok = window(LEFT, TOP, SCREEN_W * SCALE, SCREEN_H * SCALE);
    for (int y = 0; ok && y < SCREEN_H; ++y) {
        for (int x = 0; x < SCREEN_W; ++x) {
            const uint16_t colour = fb_get(frame, x, y) ? LIT : DARK;
            for (int k = 0; k < SCALE; ++k) s_rows[x * SCALE + k] = colour;
        }
        for (int k = 1; k < SCALE; ++k)
            memcpy(s_rows + k * SCREEN_W * SCALE, s_rows, SCREEN_W * SCALE * sizeof(s_rows[0]));
        ok = send(s_rows, sizeof(s_rows));
    }
    select_panel(false);
    memcpy(s_shown, frame, SCREEN_BYTES);
    s_any_shown = ok;
}
