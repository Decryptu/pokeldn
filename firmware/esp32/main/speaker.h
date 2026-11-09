/* A board's speaker, in a build with POKELDN_SPEAKER: it plays each scene.h sound cue the display
   task hands it. A cue cuts the last one short. docs/hardware_esp32.md, The speaker. */
#pragma once

#include <stdbool.h>
#include <stdint.h>

/* After panel_init: the speaker shares the board's I2C bus. False: no speaker, cues are dropped. */
bool speaker_start(void);
/* Never blocks; SOUND_NONE does nothing. */
void speaker_play(uint8_t cue);
