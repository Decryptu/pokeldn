#include "driver/gpio.h"
#include "driver/spi_master.h"
#include "esp_err.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

#include "display_backend.h"
#include "screen.h"

/* E32R40T board profile: ST7796, 480x320, landscape orientation. */
#define LCD_CS         GPIO_NUM_15
#define LCD_DC         GPIO_NUM_2
#define SPI_SCK        GPIO_NUM_14
#define SPI_MOSI       GPIO_NUM_13
#define SPI_MISO       GPIO_NUM_12
#define LCD_BACKLIGHT  GPIO_NUM_27
#define LCD_WIDTH      480
#define LCD_HEIGHT     320
#define SPI_CLOCK_HZ   40000000
#define ROWS_PER_CHUNK 16

static spi_device_handle_t s_spi;
static uint16_t s_pixels[LCD_WIDTH * ROWS_PER_CHUNK] __attribute__((aligned(4)));

static bool write_bytes(const uint8_t *data, size_t length)
{
    spi_transaction_t transaction = {
        .length = length * 8,
        .tx_buffer = data,
    };
    return spi_device_transmit(s_spi, &transaction) == ESP_OK;
}

static bool write_command(uint8_t command, const uint8_t *parameters, size_t length)
{
    gpio_set_level(LCD_DC, 0);
    if (!write_bytes(&command, 1)) return false;
    if (length) {
        gpio_set_level(LCD_DC, 1);
        if (!write_bytes(parameters, length)) return false;
    }
    return true;
}

static bool init(void)
{
    const gpio_config_t io = {
        .pin_bit_mask = (1ULL << LCD_CS) | (1ULL << LCD_DC) | (1ULL << LCD_BACKLIGHT),
        .mode = GPIO_MODE_OUTPUT,
        .pull_up_en = GPIO_PULLUP_DISABLE,
        .pull_down_en = GPIO_PULLDOWN_DISABLE,
        .intr_type = GPIO_INTR_DISABLE,
    };
    if (gpio_config(&io) != ESP_OK) return false;
    gpio_set_level(LCD_CS, 1);
    gpio_set_level(LCD_DC, 1);
    /* The TFT backlight is steady DC, not PWM. GPIO27 must not share LEDC with the status LED. */
    gpio_set_level(LCD_BACKLIGHT, 1);

    const spi_bus_config_t bus = {
        .mosi_io_num = SPI_MOSI,
        .miso_io_num = SPI_MISO,
        .sclk_io_num = SPI_SCK,
        .quadwp_io_num = -1,
        .quadhd_io_num = -1,
        .max_transfer_sz = LCD_WIDTH * ROWS_PER_CHUNK * sizeof(uint16_t),
    };
    if (spi_bus_initialize(SPI2_HOST, &bus, SPI_DMA_CH_AUTO) != ESP_OK) return false;
    const spi_device_interface_config_t device = {
        .clock_speed_hz = SPI_CLOCK_HZ,
        .mode = 0,
        .spics_io_num = -1,   /* CS spans command and pixel-data transactions. */
        .queue_size = 1,
    };
    if (spi_bus_add_device(SPI2_HOST, &device, &s_spi) != ESP_OK) return false;

    gpio_set_level(LCD_CS, 0);
    bool ok = write_command(0x01, NULL, 0); /* Software reset. */
    gpio_set_level(LCD_CS, 1);
    if (!ok) return false;
    vTaskDelay(pdMS_TO_TICKS(150));

    gpio_set_level(LCD_CS, 0);
    ok = write_command(0x11, NULL, 0); /* Sleep out. */
    gpio_set_level(LCD_CS, 1);
    if (!ok) return false;
    vTaskDelay(pdMS_TO_TICKS(120));

    gpio_set_level(LCD_CS, 0);
    const uint8_t pixel_format = 0x55; /* RGB565. */
    const uint8_t landscape = 0x28;    /* 480x320 landscape address order. */
    ok = write_command(0x3a, &pixel_format, 1) &&
         write_command(0x36, &landscape, 1) &&
         write_command(0x21, NULL, 0) &&  /* Display inversion, typical ST7796 modules. */
         write_command(0x29, NULL, 0);    /* Display on. */
    gpio_set_level(LCD_CS, 1);
    if (!ok) return false;

    return true;
}

static bool present(const uint8_t *framebuffer)
{
    const uint8_t column[] = {0x00, 0x00, (LCD_WIDTH - 1) >> 8, (LCD_WIDTH - 1) & 0xff};
    const uint8_t row[] = {0x00, 0x00, (LCD_HEIGHT - 1) >> 8, (LCD_HEIGHT - 1) & 0xff};
    gpio_set_level(LCD_CS, 0);
    bool ok = write_command(0x2a, column, sizeof(column)) &&
              write_command(0x2b, row, sizeof(row)) &&
              write_command(0x2c, NULL, 0);

    for (int y0 = 0; ok && y0 < LCD_HEIGHT; y0 += ROWS_PER_CHUNK) {
        const int rows = (y0 + ROWS_PER_CHUNK <= LCD_HEIGHT) ? ROWS_PER_CHUNK : LCD_HEIGHT - y0;
        for (int y = 0; y < rows; ++y) {
            const int source_y = (y0 + y) * SCREEN_H / LCD_HEIGHT;
            for (int x = 0; x < LCD_WIDTH; ++x) {
                const int source_x = x * SCREEN_W / LCD_WIDTH;
                /* Invert the monochrome scene: lit pixels are black on a white background. */
                s_pixels[y * LCD_WIDTH + x] = fb_get(framebuffer, source_x, source_y) ? 0x0000 : 0xffff;
            }
        }
        /* ST7796 consumes RGB565 high byte first. */
        for (int i = 0; i < rows * LCD_WIDTH; ++i)
            s_pixels[i] = (uint16_t)((s_pixels[i] << 8) | (s_pixels[i] >> 8));
        gpio_set_level(LCD_DC, 1);
        ok = write_bytes((const uint8_t *)s_pixels, rows * LCD_WIDTH * sizeof(uint16_t));
    }
    gpio_set_level(LCD_CS, 1);
    return ok;
}

static void set_power(uint8_t power)
{
    /* Scene power transitions must not pulse or dim the TFT backlight. */
    (void)power;
    gpio_set_level(LCD_BACKLIGHT, 1);
}

static const display_backend_t E32R40T = {
    .name = "E32R40T (ST7796)",
    .width = LCD_WIDTH,
    .height = LCD_HEIGHT,
    .init = init,
    .present = present,
    .set_power = set_power,
};

const display_backend_t *display_e32r40t_backend(void) { return &E32R40T; }
