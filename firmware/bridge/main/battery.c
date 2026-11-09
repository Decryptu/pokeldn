/* The LiPo on the XIAO ESP32C5's battery pads: its voltage through the board's 1:2 divider on GPIO6,
   which GPIO26 switches on. The charger (SGM40567) reports nothing to a pin, so charging is read
   from the voltage: it rises while USB charges and falls when USB goes. docs/hardware_esp32.md,
   The network bridge. */
#include "bridge.h"

#include "driver/gpio.h"
#include "esp_adc/adc_cali.h"
#include "esp_adc/adc_cali_scheme.h"
#include "esp_adc/adc_oneshot.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

#define ADC_GPIO CONFIG_BRIDGE_BATTERY_ADC_GPIO
#define EN_GPIO CONFIG_BRIDGE_BATTERY_EN_GPIO
#define SAMPLES 16
#define WINDOW_S 60        /* charging: the voltage moved this much over the last minute */
#define TREND_MV 15
#define ABSENT_MV 2500     /* below this, no cell: a LiPo is cut off far above it */

static const char *TAG = "battery";

/* present | charging << 1 | percent << 2 | millivolts << 9 */
static atomic_uint s_state;

battery_t battery_read(void)
{
    const unsigned s = atomic_load(&s_state);
    return (battery_t){.present = s & 1, .charging = s >> 1 & 1, .percent = s >> 2 & 0x7f, .mv = s >> 9};
}

/* A LiPo's resting voltage to its charge; under Wi-Fi's load it reads a little low, while charging high. */
static unsigned percent_of(unsigned mv)
{
    static const uint16_t CURVE[][2] = {{4200, 100}, {4100, 90}, {4000, 80}, {3900, 65}, {3800, 50},
                                        {3750, 40}, {3700, 30}, {3650, 20}, {3600, 10}, {3500, 5}, {3300, 0}};
    if (mv >= CURVE[0][0]) return 100;
    for (size_t i = 1; i < sizeof(CURVE) / sizeof(CURVE[0]); ++i)
        if (mv >= CURVE[i][0])
            return CURVE[i][1] + (mv - CURVE[i][0]) * (CURVE[i - 1][1] - CURVE[i][1]) / (CURVE[i - 1][0] - CURVE[i][0]);
    return 0;
}

#if ADC_GPIO >= 0
static void battery_task(void *arg)
{
    adc_unit_t unit;
    adc_channel_t channel;
    adc_oneshot_unit_handle_t adc;
    adc_cali_handle_t cali = NULL;
    if (adc_oneshot_io_to_channel(ADC_GPIO, &unit, &channel) != ESP_OK) {
        ESP_LOGW(TAG, "GPIO%d has no ADC channel", ADC_GPIO);
        vTaskDelete(NULL);
    }
    const adc_oneshot_unit_init_cfg_t unit_config = {.unit_id = unit};
    const adc_oneshot_chan_cfg_t channel_config = {.atten = ADC_ATTEN_DB_12, .bitwidth = ADC_BITWIDTH_DEFAULT};
    ESP_ERROR_CHECK(adc_oneshot_new_unit(&unit_config, &adc));
    ESP_ERROR_CHECK(adc_oneshot_config_channel(adc, channel, &channel_config));
#if ADC_CALI_SCHEME_CURVE_FITTING_SUPPORTED
    const adc_cali_curve_fitting_config_t cali_config = {
        .unit_id = unit, .chan = channel, .atten = ADC_ATTEN_DB_12, .bitwidth = ADC_BITWIDTH_DEFAULT,
    };
    if (adc_cali_create_scheme_curve_fitting(&cali_config, &cali) != ESP_OK) cali = NULL;
#endif
#if EN_GPIO >= 0
    /* The divider draws 21 uA from a full cell: little beside Wi-Fi, so it stays on. */
    gpio_reset_pin(EN_GPIO);
    gpio_set_direction(EN_GPIO, GPIO_MODE_OUTPUT);
    gpio_set_level(EN_GPIO, 1);
    vTaskDelay(pdMS_TO_TICKS(10));
#endif
    uint16_t history[WINDOW_S] = {0};
    unsigned filtered = 0, second = 0;
    bool charging = false;
    for (;; vTaskDelay(pdMS_TO_TICKS(1000))) {
        int sum = 0, n = 0;
        for (int i = 0; i < SAMPLES; ++i) {
            int raw, mv;
            if (adc_oneshot_read(adc, channel, &raw) != ESP_OK) continue;
            if (!cali || adc_cali_raw_to_voltage(cali, raw, &mv) != ESP_OK) mv = raw * 3300 / 4095;
            sum += mv, ++n;
        }
        if (!n) continue;
        const unsigned mv = 2 * sum / n;   /* the 1:2 divider */
        filtered = filtered ? (filtered * 7 + mv) / 8 : mv;
        const unsigned before = history[second % WINDOW_S];
        history[second++ % WINDOW_S] = filtered;
        if (before && filtered >= before + TREND_MV) charging = true;
        else if (before && before >= filtered + TREND_MV) charging = false;
        const bool present = filtered >= ABSENT_MV;
        atomic_store(&s_state, present | (present && charging) << 1 | percent_of(filtered) << 2 | filtered << 9);
    }
}
#endif

void battery_start(void)
{
#if ADC_GPIO >= 0
    xTaskCreate(battery_task, "battery", 3072, NULL, 1, NULL);
#endif
}
