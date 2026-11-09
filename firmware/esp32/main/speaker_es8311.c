/* The szpi board's speaker: an ES8311 codec on I2C 0x18 and I2S (MCLK 38, BCLK 14, WS 13, DOUT 45),
   its amplifier behind the PCA9557 [xiaozhi-esp32 boards/lckfb/szpi-esp32s3]. Register values follow
   Espressif's es8311 driver for slave mode, 16 bits, MCLK 256 fs at 16 kHz [esp-bsp components/es8311]. */
#include "driver/i2s_std.h"
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "freertos/task.h"

#include "board_szpi.h"
#include "scene.h"
#include "sfx.h"
#include "speaker.h"

#define ES8311 0x18
#define CHUNK 160           /* 10 ms */
#define IDLE_MS 600         /* the amplifier goes off this long after the last cue */

/* After the reset pair 00=1F, 00=00 (20 ms apart): clocks from MCLK, the 4.096 MHz / 16 kHz row of
   the driver's coefficient table, slave I2S at 16 bits, DAC and output powered, DAC EQ bypassed, 0 dB,
   unmuted. */
static const uint8_t INIT[][2] = {
    {0x00, 0x80}, {0x01, 0x3f}, {0x02, 0x00}, {0x03, 0x10}, {0x04, 0x10}, {0x05, 0x00}, {0x06, 0x03},
    {0x07, 0x00}, {0x08, 0xff}, {0x09, 0x0c}, {0x0a, 0x0c}, {0x0d, 0x01}, {0x0e, 0x02}, {0x12, 0x00},
    {0x13, 0x10}, {0x1c, 0x6a}, {0x37, 0x08}, {0x32, 0xbf}, {0x31, 0x00},
};

static QueueHandle_t s_cues;
static i2s_chan_handle_t s_tx;

static bool codec_write(i2c_master_dev_handle_t dev, uint8_t reg, uint8_t value)
{
    const uint8_t bytes[] = {reg, value};
    return i2c_master_transmit(dev, bytes, sizeof(bytes), 50) == ESP_OK;
}

static bool codec_start(void)
{
    const i2c_device_config_t config = {
        .dev_addr_length = I2C_ADDR_BIT_LEN_7, .device_address = ES8311, .scl_speed_hz = 400000,
    };
    i2c_master_dev_handle_t dev;
    if (!board_szpi_bus() || i2c_master_bus_add_device(board_szpi_bus(), &config, &dev) != ESP_OK) return false;
    if (!codec_write(dev, 0x00, 0x1f)) return false;
    vTaskDelay(pdMS_TO_TICKS(20));
    if (!codec_write(dev, 0x00, 0x00)) return false;
    for (size_t i = 0; i < sizeof(INIT) / sizeof(INIT[0]); ++i)
        if (!codec_write(dev, INIT[i][0], INIT[i][1])) return false;
    return true;
}

static bool i2s_start(void)
{
    const i2s_chan_config_t chan = I2S_CHANNEL_DEFAULT_CONFIG(I2S_NUM_0, I2S_ROLE_MASTER);
    i2s_std_config_t std = {
        .clk_cfg = I2S_STD_CLK_DEFAULT_CONFIG(SFX_RATE),
        .slot_cfg = I2S_STD_PHILIPS_SLOT_DEFAULT_CONFIG(I2S_DATA_BIT_WIDTH_16BIT, I2S_SLOT_MODE_STEREO),
        .gpio_cfg = {.mclk = 38, .bclk = 14, .ws = 13, .dout = 45, .din = I2S_GPIO_UNUSED},
    };
    std.clk_cfg.mclk_multiple = I2S_MCLK_MULTIPLE_256;
    return i2s_new_channel(&chan, &s_tx, NULL) == ESP_OK && i2s_channel_init_std_mode(s_tx, &std) == ESP_OK &&
           i2s_channel_enable(s_tx) == ESP_OK;
}

/* Both slots carry the mono sound; the codec plays the left one. */
static void write_chunk(const int16_t *mono, size_t n)
{
    int16_t frames[2 * CHUNK];
    for (size_t i = 0; i < n; ++i) frames[2 * i] = frames[2 * i + 1] = mono[i];
    size_t written;
    i2s_channel_write(s_tx, frames, n * 2 * sizeof(int16_t), &written, pdMS_TO_TICKS(100));
}

static void speaker_task(void *arg)
{
    int16_t mono[CHUNK];
    uint8_t cue = SOUND_NONE;
    for (;;) {
        if (cue == SOUND_NONE) {
            if (xQueueReceive(s_cues, &cue, pdMS_TO_TICKS(IDLE_MS)) != pdTRUE) {
                board_szpi_amplifier(false);
                xQueueReceive(s_cues, &cue, portMAX_DELAY);
            }
            board_szpi_amplifier(true);
        }
        const uint8_t playing = cue;
        cue = SOUND_NONE;
        for (size_t at = 0, n; (n = sfx_render(playing, at, mono, CHUNK)); at += n) {
            write_chunk(mono, n);
            if (xQueueReceive(s_cues, &cue, 0) == pdTRUE) break;   /* a new cue cuts this one short */
        }
        for (size_t i = 0; i < CHUNK; ++i) mono[i] = 0;
        write_chunk(mono, CHUNK);   /* the DMA buffers end on silence, not on the cue's last samples */
    }
}

bool speaker_start(void)
{
    if (!codec_start() || !i2s_start()) return false;
    s_cues = xQueueCreate(4, sizeof(uint8_t));
    return xTaskCreatePinnedToCore(speaker_task, "speaker", 3072, NULL, 1, NULL, configNUMBER_OF_CORES - 1) == pdPASS;
}

void speaker_play(uint8_t cue)
{
    if (s_cues && cue != SOUND_NONE && cue < SOUNDS) xQueueSend(s_cues, &cue, 0);
}
