/* An optional SSD1306 128x64 OLED on I2C (ESP32: SDA GPIO21, SCL GPIO22), redrawn by a priority-1
   task on the last core. A board without one probes nothing at 0x3C/0x3D and starts no task.
   docs/hardware_esp32.md, The screen. */
#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "scene.h"

/* Called before each frame to fill in the radio's state. */
typedef void (*display_state_t)(scene_radio_t *state);

/* True when a screen answered. */
bool display_start(display_state_t state);
/* A DISPLAY command, handed to the screen's task; false when it was not taken (no screen, a full
   queue). Never blocks the caller. */
bool display_command(const uint8_t *payload, size_t length);
void display_reset(void);
