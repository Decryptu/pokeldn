/* Hardware-independent contract between the display task and a display profile. */
#pragma once

#include <stdbool.h>
#include <stdint.h>

#include "scene.h"

/* Each profile owns its pins, controller initialization, frame transfer, and backlight policy. */
typedef struct {
    const char *name;
    uint16_t width;
    uint16_t height;
    bool (*init)(void);
    bool (*present)(const uint8_t *framebuffer);
    void (*set_power)(uint8_t power);
} display_backend_t;

const display_backend_t *display_oled_backend(void);
const display_backend_t *display_e32r40t_backend(void);
