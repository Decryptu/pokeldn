/* The blue LED: LEDC PWM on GPIO2, recomputed every 10 ms by a priority-1 task on core 1, below the
   wire tasks (19 to 21). It reads counters the radio already keeps and adds nothing to the frame
   paths. docs/hardware_esp32.md, The board's LED and buttons. */
#include <math.h>
#include <stdbool.h>

#include "driver/gpio.h"
#include "driver/ledc.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

#include "led.h"

#define LED_GPIO 2
#define BUTTON_GPIO 0   /* BOOT: low while pressed, pulled up */
#define BUTTON_TICKS 3  /* 30 ms of one level makes it the button's state */
#define DUTY_MAX 8191   /* 13 bits at 5 kHz */
#define TICK_MS 10
#define CROSSFADE_MS 150

static const uint16_t DEFAULT_PERIOD_MS[LED_PATTERNS] = {
    [LED_BREATHE] = 3000, [LED_BLINK] = 1000, [LED_FLASH3] = 1000, [LED_RAMP_UP] = 1000,
    [LED_RAMP_DOWN] = 1000, [LED_PULSE] = 1200,
};

static portMUX_TYPE s_lock = portMUX_INITIALIZER_UNLOCKED;
static led_look_t s_host = {LED_PULSE, 255, 900};   /* the boot pulse */
static int64_t s_host_until_ms = 900;               /* 0: held until the next command */
static uint32_t s_host_serial = 1;                  /* restarts the look when the host resends it */
static led_state_t s_state;
static led_button_t s_button;

static int64_t now_ms(void) { return esp_timer_get_time() / 1000; }

static float clamp01(float x) { return x < 0 ? 0 : x > 1 ? 1 : x; }
static float smooth(float x) { x = clamp01(x); return x * x * (3 - 2 * x); }
static float ease_in_out(float x)
{
    x = clamp01(x);
    return x < 0.5f ? 4 * x * x * x : 1 - powf(2 - 2 * x, 3) / 2;
}

/* A soft square: on over [0, width) with eased edges `edge` long, off after. */
static float soft_on(float p, float width, float edge)
{
    return p < width ? fminf(smooth(p / edge), smooth((width - p) / edge)) : 0;
}

/* Brightness 0..1 of a pattern `t` ms into it. */
static float level(const led_look_t *look, int64_t t)
{
    const float period = look->period_ms ? look->period_ms : DEFAULT_PERIOD_MS[look->pattern];
    const float p = period > 0 ? fmodf((float)t, period) / period : 0;
    const float once = period > 0 ? (float)t / period : 1;
    switch (look->pattern) {
    case LED_ON: return 1;
    case LED_BREATHE: return 0.5f - 0.5f * cosf(2 * (float)M_PI * p);
    case LED_BLINK: return soft_on(p, 0.5f, 0.08f);
    case LED_FLASH3: {
        const float slot = p / 0.2f;
        return slot < 3 ? soft_on(slot - floorf(slot), 0.5f, 0.1f) : 0;
    }
    case LED_RAMP_UP: return ease_in_out(once);
    case LED_RAMP_DOWN: return 1 - ease_in_out(once);
    case LED_PULSE: return p < 0.15f ? 1 - powf(1 - p / 0.15f, 2) : powf(1 - (p - 0.15f) / 0.85f, 3);
    default: return 0;
    }
}

static bool same_look(const led_look_t *a, const led_look_t *b)
{
    return a->pattern == b->pattern && a->peak == b->peak && a->period_ms == b->period_ms;
}

static void led_task(void *arg)
{
    led_look_t shown = {LED_OFF, 0, 0};
    int64_t look_started = now_ms(), fade_started = look_started;
    float fade_from = 0, output = 0, flash = 0, press_flash = 0;
    bool pressed = false;
    int same_level = 0, last_level = 1;
    uint32_t presses = 0;
    uint32_t last_activity = 0, last_alarm = 0, last_serial = 0;
    int64_t alarm_until = 0;
    TickType_t wake = xTaskGetTickCount();
    for (;;) {
        const int64_t now = now_ms();
        const int button_level = gpio_get_level(BUTTON_GPIO);
        same_level = button_level == last_level ? same_level + 1 : 0;
        last_level = button_level;
        if (same_level == BUTTON_TICKS && pressed != (button_level == 0)) {
            pressed = button_level == 0;
            if (pressed) {
                press_flash = 1;
                if (s_button) s_button(++presses, esp_timer_get_time());
            }
        }
        led_look_t look, host;
        uint32_t serial;
        taskENTER_CRITICAL(&s_lock);
        if (s_host.pattern != LED_AUTO && s_host_until_ms && now >= s_host_until_ms)
            s_host.pattern = LED_AUTO;
        host = s_host;
        serial = s_host_serial;
        taskEXIT_CRITICAL(&s_lock);

        uint32_t activity = last_activity, alarm = last_alarm;
        led_look_t automatic = {LED_OFF, 0, 0};
        if (s_state) s_state(&automatic, &activity, &alarm);
        if (alarm != last_alarm) alarm_until = now + 1500;
        last_alarm = alarm;

        const bool is_auto = host.pattern == LED_AUTO;
        if (!is_auto) look = host;
        else if (now < alarm_until) look = (led_look_t){LED_FLASH3, 255, 750};
        else look = automatic;
        if (!same_look(&look, &shown) || serial != last_serial) {
            fade_from = output;
            fade_started = look_started = now;
            shown = look;
            last_serial = serial;
        }
        const float target = level(&shown, now - look_started) * shown.peak / 255.0f;
        const float mix = smooth((float)(now - fade_started) / CROSSFADE_MS);
        output = fade_from + (target - fade_from) * mix;

        /* A flicker per frame, retriggered only once the last has faded: a flood reads as a fast
           shimmer rather than a steady light. */
        if (is_auto && activity != last_activity && flash < 0.25f) flash = 1;
        last_activity = activity;
        /* A press answers with a full flash over any look, so the player sees it was taken. */
        const float shown_level = fmaxf(fmaxf(output, is_auto ? flash * 0.7f : 0), press_flash);
        flash *= 0.8f;
        press_flash *= 0.9f;

        ledc_set_duty(LEDC_LOW_SPEED_MODE, LEDC_CHANNEL_0,
                      (uint32_t)lroundf(powf(clamp01(shown_level), 2.2f) * DUTY_MAX));
        ledc_update_duty(LEDC_LOW_SPEED_MODE, LEDC_CHANNEL_0);
        vTaskDelayUntil(&wake, pdMS_TO_TICKS(TICK_MS));
    }
}

bool led_set(uint8_t pattern, uint8_t peak, uint16_t period_ms, uint16_t duration_ms)
{
    if (pattern >= LED_PATTERNS) return false;
    const int64_t until = duration_ms ? now_ms() + duration_ms : 0;
    taskENTER_CRITICAL(&s_lock);
    s_host = (led_look_t){pattern, peak, period_ms};
    s_host_until_ms = until;
    ++s_host_serial;
    taskEXIT_CRITICAL(&s_lock);
    return true;
}

void led_start(led_state_t state, led_button_t button)
{
    s_state = state;
    s_button = button;
    const gpio_config_t input = {
        .pin_bit_mask = 1ULL << BUTTON_GPIO, .mode = GPIO_MODE_INPUT,
        .pull_up_en = GPIO_PULLUP_ENABLE, .pull_down_en = GPIO_PULLDOWN_DISABLE,
        .intr_type = GPIO_INTR_DISABLE,
    };
    gpio_config(&input);
    const ledc_timer_config_t timer = {
        .speed_mode = LEDC_LOW_SPEED_MODE, .duty_resolution = LEDC_TIMER_13_BIT,
        .timer_num = LEDC_TIMER_0, .freq_hz = 5000, .clk_cfg = LEDC_AUTO_CLK,
    };
    const ledc_channel_config_t channel = {
        .gpio_num = LED_GPIO, .speed_mode = LEDC_LOW_SPEED_MODE, .channel = LEDC_CHANNEL_0,
        .timer_sel = LEDC_TIMER_0, .duty = 0, .hpoint = 0,
    };
    /* A board without the LED still runs: the radio never depends on it. */
    if (ledc_timer_config(&timer) != ESP_OK || ledc_channel_config(&channel) != ESP_OK) return;
    s_host_until_ms = now_ms() + 900;
    xTaskCreatePinnedToCore(led_task, "led", 3072, NULL, 1, NULL, 1);
}
