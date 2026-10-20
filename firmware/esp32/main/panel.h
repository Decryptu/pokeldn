/* The panel the display task draws on: one of panel_oled.c or panel_e32r40t.c, picked by
   POKELDN_DISPLAY at build time. docs/hardware_esp32.md, The screen. */
#pragma once

#include <stdbool.h>
#include <stdint.h>

bool panel_init(void);                          /* false: no panel, the pins are left as they were */
void panel_present(const uint8_t *frame);       /* SCREEN_BYTES, screen.h's layout */
bool panel_power(uint8_t power);                /* enum scene_power; false: retried next frame */
