#include <stdlib.h>
#include <string.h>

#include "driver/i2c_master.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "freertos/task.h"

#include "display.h"
#include "screen.h"

/* The pins the usual pinouts name for I2C: DevKit V1 D21/D22, XIAO D4/D5. */
#if CONFIG_IDF_TARGET_ESP32
#define SDA_GPIO 21
#define SCL_GPIO 22
#elif CONFIG_IDF_TARGET_ESP32S3
#define SDA_GPIO 8
#define SCL_GPIO 9
#elif CONFIG_IDF_TARGET_ESP32C3
#define SDA_GPIO 6
#define SCL_GPIO 7
#elif CONFIG_IDF_TARGET_ESP32C6
#define SDA_GPIO 22
#define SCL_GPIO 23
#endif
#define FRAME_MS 50

/* Panel wiring per the module's sheet: segment 127 is column 1 (A1), COM0 is row 63 (C8). */
static const uint8_t INIT[] = {
    0x00,                   /* control byte: commands follow */
    0xae, 0xd5, 0x80, 0xa8, 0x3f, 0xd3, 0x00, 0x40, 0x8d, 0x14, 0x20, 0x00, 0xa1, 0xc8,
    0xda, 0x12, 0x81, 0xcf, 0xd9, 0xf1, 0xdb, 0x40, 0xa4, 0xa6, 0x2e, 0xaf,
};
static const uint8_t WINDOW[] = {0x00, 0x21, 0x00, 0x7f, 0x22, 0x00, 0x07};
/* By enum scene_power: INIT's contrast and pre-charge; dim; off, RAM kept. On the 0.96-inch module
   contrast 0 is black and pre-charge 1+1 clocks (D9 11) flickers. docs/hardware_esp32.md, The screen. */
static const uint8_t POWER[][6] = {
    {0x00, 0x81, 0xcf, 0xd9, 0xf1, 0xaf}, {0x00, 0x81, 0x01, 0xd9, 0x22, 0xaf}, {0x00, 0xae},
};
static const size_t POWER_LEN[] = {6, 6, 2};

typedef struct {
    uint16_t length;       /* 0: reset */
    uint8_t *payload;
} display_msg_t;

static i2c_master_dev_handle_t s_dev;
static QueueHandle_t s_commands;
static display_state_t s_state;
static uint8_t s_power = SCENE_ON;   /* INIT's */
static uint8_t s_frame[1 + SCREEN_BYTES] = {0x40};   /* control byte: data follows */

static void display_task(void *arg)
{
    TickType_t wake = xTaskGetTickCount();
    for (;;) {
        const uint32_t now = (uint32_t)(esp_timer_get_time() / 1000);
        display_msg_t msg;
        while (xQueueReceive(s_commands, &msg, 0) == pdTRUE) {
            if (msg.length) scene_command(msg.payload, msg.length, now);
            else scene_reset();
            free(msg.payload);
        }
        scene_radio_t state = {0};
        if (s_state) s_state(&state);
        const uint8_t power = scene_draw(s_frame + 1, &state, now);
        /* The frame goes before the panel lights, so waking never shows the last one. */
        if (power != SCENE_OFF && i2c_master_transmit(s_dev, WINDOW, sizeof(WINDOW), 50) == ESP_OK)
            i2c_master_transmit(s_dev, s_frame, sizeof(s_frame), 100);
        if (power != s_power && i2c_master_transmit(s_dev, POWER[power], POWER_LEN[power], 50) == ESP_OK)
            s_power = power;
        vTaskDelayUntil(&wake, pdMS_TO_TICKS(FRAME_MS));
    }
}

bool display_start(display_state_t state)
{
#ifdef SDA_GPIO
    const i2c_master_bus_config_t bus_config = {
        .i2c_port = -1, .sda_io_num = SDA_GPIO, .scl_io_num = SCL_GPIO,
        .clk_source = I2C_CLK_SRC_DEFAULT, .glitch_ignore_cnt = 7,
        .flags.enable_internal_pullup = true,
    };
    i2c_master_bus_handle_t bus;
    if (i2c_new_master_bus(&bus_config, &bus) != ESP_OK) return false;
    uint16_t address = 0x3c;
    if (i2c_master_probe(bus, address, 20) != ESP_OK && i2c_master_probe(bus, ++address, 20) != ESP_OK) {
        i2c_del_master_bus(bus);   /* frees the pins: a board without a screen is left as it was */
        return false;
    }
    const i2c_device_config_t dev_config = {
        .dev_addr_length = I2C_ADDR_BIT_LEN_7, .device_address = address, .scl_speed_hz = 400000,
    };
    if (i2c_master_bus_add_device(bus, &dev_config, &s_dev) != ESP_OK ||
        i2c_master_transmit(s_dev, INIT, sizeof(INIT), 100) != ESP_OK) return false;
    s_state = state;
    s_commands = xQueueCreate(8, sizeof(display_msg_t));
    xTaskCreatePinnedToCore(display_task, "display", 3072, NULL, 1, NULL, configNUMBER_OF_CORES - 1);
    return true;
#else
    (void)state;
    return false;
#endif
}

/* Copied and queued: the wire's reader never waits on a frame being drawn. */
bool display_command(const uint8_t *payload, size_t length)
{
    if (!s_commands || !length || length > 1024) return false;
    display_msg_t msg = {.length = (uint16_t)length, .payload = malloc(length)};
    if (!msg.payload) return false;
    memcpy(msg.payload, payload, length);
    if (xQueueSend(s_commands, &msg, 0) == pdTRUE) return true;
    free(msg.payload);
    return false;
}

void display_reset(void)
{
    const display_msg_t msg = {0};
    if (s_commands) xQueueSend(s_commands, &msg, 0);
}
