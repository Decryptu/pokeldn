/* The board's blue LED on GPIO2, driven by LEDC PWM from a low-priority task at 100 Hz.
   The looks and the LED command are in docs/hardware_esp32.md, The board's LED and buttons. */
#pragma once

#include <stdbool.h>
#include <stdint.h>

enum led_pattern {
    LED_AUTO,        /* the look the radio's state picks, with a flicker per frame */
    LED_OFF,
    LED_ON,
    LED_BREATHE,     /* raised cosine */
    LED_BLINK,       /* half the period on, with eased edges */
    LED_FLASH3,      /* three short flashes, then dark for the rest of the period */
    LED_RAMP_UP,     /* once over the period, ease-in-out, then held */
    LED_RAMP_DOWN,
    LED_PULSE,       /* a quick swell and a slow cubic fall, repeated */
    LED_PATTERNS,
};

typedef struct {
    uint8_t pattern, peak;   /* peak brightness 0..255, perceptual (gamma 2.2) */
    uint16_t period_ms;
} led_look_t;

/* Called every tick from the LED task: the automatic look, a counter that moves on every frame
   sent or received, and a counter that moves on every fault worth a warning. */
typedef void (*led_state_t)(led_look_t *look, uint32_t *activity, uint32_t *alarm);

void led_start(led_state_t state);
/* The host's look for duration_ms (0: until the next call); LED_AUTO hands the LED back. A period
   of 0 is the pattern's default. False for an unknown pattern. */
bool led_set(uint8_t pattern, uint8_t peak, uint16_t period_ms, uint16_t duration_ms);
