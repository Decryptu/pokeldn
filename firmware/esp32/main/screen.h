/* Drawing into a 128x64 one-bit frame in the SSD1306's page order: byte x + 128 * (y / 8), bit y % 8.
   Nothing here touches hardware, so the host compiles it for previews (tools/ldn/screen_preview.py). */
#pragma once

#include <stdbool.h>
#include <stdint.h>

#define SCREEN_W 128
#define SCREEN_H 64
#define SCREEN_BYTES (SCREEN_W * SCREEN_H / 8)

void fb_clear(uint8_t *fb);
void fb_pixel(uint8_t *fb, int x, int y, bool on);
bool fb_get(const uint8_t *fb, int x, int y);
void fb_fill(uint8_t *fb, int x, int y, int w, int h, bool on);
void fb_rect(uint8_t *fb, int x, int y, int w, int h);
void fb_line(uint8_t *fb, int x0, int y0, int x1, int y1);
void fb_circle(uint8_t *fb, int cx, int cy, int r, bool filled, bool on);
/* A row-major one-bit image, rows padded to whole bytes, MSB first; set bits drawn at `scale`. */
void fb_image(uint8_t *fb, int x, int y, int w, int h, const uint8_t *bits, int scale);
/* 5x7 glyphs on a 6-pixel pitch; returns the x after the text. */
int fb_text(uint8_t *fb, int x, int y, const char *text, int scale);
int fb_text_width(const char *text, int scale);
void fb_text_centered(uint8_t *fb, int y, const char *text, int scale);
