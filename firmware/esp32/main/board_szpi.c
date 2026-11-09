#include "board_szpi.h"

#define SDA 1
#define SCL 2
#define PCA9557 0x19
#define PCA_OUTPUT 0x01
#define PCA_CONFIG 0x03
#define BIT_LCD_CS 0        /* low: the panel is selected; it is the only device on its SPI bus */
#define BIT_AMPLIFIER 1     /* high: the speaker's amplifier is on */
#define BIT_CAMERA_PWDN 2   /* high: the camera is powered down */

static i2c_master_bus_handle_t s_bus;
static i2c_master_dev_handle_t s_pca;
static uint8_t s_output;

static bool write(uint8_t reg, uint8_t value)
{
    const uint8_t bytes[] = {reg, value};
    return i2c_master_transmit(s_pca, bytes, sizeof(bytes), 50) == ESP_OK;
}

bool board_szpi_start(void)
{
    if (s_pca) return true;
    const i2c_master_bus_config_t bus_config = {
        .i2c_port = -1, .sda_io_num = SDA, .scl_io_num = SCL, .clk_source = I2C_CLK_SRC_DEFAULT,
        .glitch_ignore_cnt = 7, .flags.enable_internal_pullup = true,
    };
    const i2c_device_config_t pca = {
        .dev_addr_length = I2C_ADDR_BIT_LEN_7, .device_address = PCA9557, .scl_speed_hz = 400000,
    };
    if (i2c_new_master_bus(&bus_config, &s_bus) != ESP_OK) return false;
    if (i2c_master_bus_add_device(s_bus, &pca, &s_pca) != ESP_OK) return false;
    /* Outputs first, then directions: the pins leave input mode already at their levels. */
    s_output = 1 << BIT_CAMERA_PWDN;
    if (!write(PCA_OUTPUT, s_output) ||
        !write(PCA_CONFIG, (uint8_t)~(1 << BIT_LCD_CS | 1 << BIT_AMPLIFIER | 1 << BIT_CAMERA_PWDN))) {
        s_pca = NULL;
        return false;
    }
    return true;
}

i2c_master_bus_handle_t board_szpi_bus(void) { return s_bus; }

bool board_szpi_amplifier(bool on)
{
    if (!s_pca) return false;
    const uint8_t output = on ? s_output | 1 << BIT_AMPLIFIER : s_output & ~(1 << BIT_AMPLIFIER);
    if (output == s_output) return true;
    if (!write(PCA_OUTPUT, output)) return false;
    s_output = output;
    return true;
}
