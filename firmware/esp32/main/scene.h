/* What the screen shows: the radio's own state, or a trade or a gift the host describes with
   DISPLAY (0x0E). Host-compilable like screen.c. docs/hardware_esp32.md, The screen. */
#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

enum scene_mode { SCENE_IDLE, SCENE_JOINING, SCENE_JOINED, SCENE_HOSTING, SCENE_SNIFFING };

typedef struct {
    uint8_t mode;          /* enum scene_mode */
    uint8_t stations;      /* consoles seated while hosting */
    uint32_t rx, tx;       /* data frames received and sent since boot */
} scene_radio_t;

/* DISPLAY ops. SHOW: u8 show, u16 hold s (0: until the next show), title, NUL, line, NUL.
   SPRITE: u8 slot, u8 width <= 64, u8 height <= 64, rows of (width + 7) / 8 bytes, MSB first. */
enum { DISPLAY_OP_SHOW, DISPLAY_OP_SPRITE };
enum { SHOW_AUTO, SHOW_TRADE, SHOW_TRADED, SHOW_GIFT, SHOW_GIFTED, SHOWS };
enum { SLOT_OURS, SLOT_THEIRS, SLOT_GIFT, SLOTS };
#define SPRITE_W 64
#define SPRITE_H 64

/* False for a malformed command. */
bool scene_command(const uint8_t *payload, size_t length, uint32_t now_ms);
/* Back to the radio's own scenes and no sprites: a new host session. */
void scene_reset(void);
void scene_draw(uint8_t *fb, const scene_radio_t *radio, uint32_t now_ms);
