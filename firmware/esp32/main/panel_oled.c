/* An SSD1306 128x64 (or the C3 board's 72x40) on I2C, probed at boot. */
#include <string.h>

#include "driver/i2c_master.h"

#include "panel.h"
#include "scene.h"
#include "screen.h"

/* Probed in order: the pins the usual pinouts name for I2C (DevKit V1 D21/D22, XIAO D4/D5), then
   the 0.42-inch ESP32-C3 board's panel on GPIO5/6 [Zephyr esp32c3_042_oled-pinctrl.dtsi]. */
static const struct {
    uint8_t sda, scl, panel;
} PINS[] = {
#if CONFIG_IDF_TARGET_ESP32
    {21, 22, PANEL_128X64},
#elif CONFIG_IDF_TARGET_ESP32S3
    {8, 9, PANEL_128X64},
#elif CONFIG_IDF_TARGET_ESP32C3
    {6, 7, PANEL_128X64}, {5, 6, PANEL_72X40},
#elif CONFIG_IDF_TARGET_ESP32C6
    {22, 23, PANEL_128X64},
#endif
};

/* Panel wiring per the module's sheet: segment 127 is column 1 (A1), COM0 is row 63 (C8). The 72x40
   panel shows columns 30..101, rows 24..63 of the same frame. docs/hardware_esp32.md, The screen. */
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

static i2c_master_dev_handle_t s_dev;
static uint8_t s_frame[1 + SCREEN_BYTES] = {0x40};   /* control byte: data follows */

bool panel_init(void)
{
    for (size_t i = 0; i < sizeof(PINS) / sizeof(PINS[0]); ++i) {
        const i2c_master_bus_config_t bus_config = {
            .i2c_port = -1, .sda_io_num = PINS[i].sda, .scl_io_num = PINS[i].scl,
            .clk_source = I2C_CLK_SRC_DEFAULT, .glitch_ignore_cnt = 7,
            .flags.enable_internal_pullup = true,
        };
        i2c_master_bus_handle_t bus;
        if (i2c_new_master_bus(&bus_config, &bus) != ESP_OK) continue;
        uint16_t address = 0x3c;
        if (i2c_master_probe(bus, address, 20) != ESP_OK && i2c_master_probe(bus, ++address, 20) != ESP_OK) {
            i2c_del_master_bus(bus);   /* frees the pins: a board without a screen is left as it was */
            continue;
        }
        const i2c_device_config_t dev_config = {
            .dev_addr_length = I2C_ADDR_BIT_LEN_7, .device_address = address, .scl_speed_hz = 400000,
        };
        if (i2c_master_bus_add_device(bus, &dev_config, &s_dev) != ESP_OK ||
            i2c_master_transmit(s_dev, INIT, sizeof(INIT), 100) != ESP_OK) return false;
        scene_panel(PINS[i].panel);
        return true;
    }
    return false;
}

void panel_present(const uint8_t *frame)
{
    memcpy(s_frame + 1, frame, SCREEN_BYTES);
    if (i2c_master_transmit(s_dev, WINDOW, sizeof(WINDOW), 50) == ESP_OK)
        i2c_master_transmit(s_dev, s_frame, sizeof(s_frame), 100);
}

bool panel_power(uint8_t power)
{
    return i2c_master_transmit(s_dev, POWER[power], POWER_LEN[power], 50) == ESP_OK;
}
