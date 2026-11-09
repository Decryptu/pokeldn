/* The board's sounds, synthesised: square waves and noise in the style of a handheld's sound chip, one
   short sequence per scene.h enum scene_sound. Nothing here touches hardware, so the host compiles it
   for previews (tools/ldn/screen_preview.py --sounds). docs/hardware_esp32.md, The speaker. */
#pragma once

#include <stddef.h>
#include <stdint.h>

#define SFX_RATE 16000

/* Mono 16-bit samples of `cue` from sample `from`, at most `max` of them; 0 once the cue has ended. */
size_t sfx_render(uint8_t cue, size_t from, int16_t *out, size_t max);
/* The cue's whole length in samples. */
size_t sfx_length(uint8_t cue);
