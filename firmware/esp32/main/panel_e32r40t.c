/* The E32R40T board's 480x320 ST7796S on SPI [lcdwiki.com 4.0inch_ESP32-32E_Display]: the 128x64 frame
   drawn three times larger in the middle, lit pixels black on white. Built with POKELDN_DISPLAY=E32R40T.
   docs/hardware_esp32.md, The screen. */
#include <string.h>

#include "driver/gpio.h"
#include "driver/spi_master.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

#include "panel.h"
#include "scene.h"
#include "screen.h"

#define LCD_CS        GPIO_NUM_15
#define LCD_DC        GPIO_NUM_2    /* the classic board's LED pin: led.c uses the blue RGB LED here */
#define LCD_SCK       GPIO_NUM_14
#define LCD_MOSI      GPIO_NUM_13
#define LCD_BACKLIGHT GPIO_NUM_27   /* lit while high */
#define LCD_W 480
#define LCD_H 320
#define SCALE 3
#define LEFT ((LCD_W - SCREEN_W * SCALE) / 2)
#define TOP ((LCD_H - SCREEN_H * SCALE) / 2)
#define BLACK 0x0000                /* both colours read the same in either byte order */
#define WHITE 0xffff

static spi_device_handle_t s_spi;
static uint16_t s_rows[SCREEN_W * SCALE * SCALE];   /* one frame row, three panel rows */
static uint8_t s_shown[SCREEN_BYTES];
static bool s_any_shown;

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

bool panel_init(void)
{
    const gpio_config_t io = {
        .pin_bit_mask = 1ULL << LCD_CS | 1ULL << LCD_DC | 1ULL << LCD_BACKLIGHT, .mode = GPIO_MODE_OUTPUT,
    };
    if (gpio_config(&io) != ESP_OK) return false;
    gpio_set_level(LCD_CS, 1);
    const spi_bus_config_t bus = {
        .mosi_io_num = LCD_MOSI, .miso_io_num = -1, .sclk_io_num = LCD_SCK,
        .quadwp_io_num = -1, .quadhd_io_num = -1, .max_transfer_sz = sizeof(s_rows),
    };
    const spi_device_interface_config_t device = {
        .clock_speed_hz = 40000000, .mode = 0, .spics_io_num = -1, .queue_size = 1,
    };
    if (spi_bus_initialize(SPI2_HOST, &bus, SPI_DMA_CH_AUTO) != ESP_OK ||
        spi_bus_add_device(SPI2_HOST, &device, &s_spi) != ESP_OK) return false;

    gpio_set_level(LCD_CS, 0);
    const uint8_t rgb565 = 0x55, landscape = 0x28;
    bool ok = command(0x01, NULL, 0);                     /* software reset */
    vTaskDelay(pdMS_TO_TICKS(150));
    ok = ok && command(0x11, NULL, 0);                    /* sleep out */
    vTaskDelay(pdMS_TO_TICKS(120));
    ok = ok && command(0x3a, &rgb565, 1) && command(0x36, &landscape, 1) &&
         command(0x21, NULL, 0) && window(0, 0, LCD_W, LCD_H);   /* 0x21: these IPS modules need inversion */
    for (int i = 0; i < SCREEN_W * SCALE * SCALE; ++i) s_rows[i] = WHITE;
    for (size_t left = LCD_W * LCD_H; ok && left; ) {
        const size_t n = left < SCREEN_W * SCALE * SCALE ? left : SCREEN_W * SCALE * SCALE;
        ok = send(s_rows, n * 2);
        left -= n;
    }
    ok = ok && command(0x29, NULL, 0);                    /* display on */
    gpio_set_level(LCD_CS, 1);
    gpio_set_level(LCD_BACKLIGHT, ok);
    return ok;
}

/* About 150 KB a frame over SPI: an unchanged frame is not sent again. */
void panel_present(const uint8_t *frame)
{
    if (s_any_shown && !memcmp(frame, s_shown, SCREEN_BYTES)) return;
    gpio_set_level(LCD_CS, 0);
    bool ok = window(LEFT, TOP, SCREEN_W * SCALE, SCREEN_H * SCALE);
    for (int y = 0; ok && y < SCREEN_H; ++y) {
        for (int x = 0; x < SCREEN_W; ++x) {
            const uint16_t colour = fb_get(frame, x, y) ? BLACK : WHITE;
            for (int k = 0; k < SCALE; ++k) s_rows[x * SCALE + k] = colour;
        }
        for (int k = 1; k < SCALE; ++k)
            memcpy(s_rows + k * SCREEN_W * SCALE, s_rows, SCREEN_W * SCALE * sizeof(s_rows[0]));
        ok = send(s_rows, sizeof(s_rows));
    }
    gpio_set_level(LCD_CS, 1);
    memcpy(s_shown, frame, SCREEN_BYTES);
    s_any_shown = ok;
}

/* No dim step: the backlight is on or off. */
bool panel_power(uint8_t power)
{
    gpio_set_level(LCD_BACKLIGHT, power != SCENE_OFF);
    return true;
}
