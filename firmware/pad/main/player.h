// The controller state and the macro player every transport shares (docs/hardware_pad.md).
#pragma once
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

// buttons u16 LE (HORI bits), hat (8 = centre), LX LY RX RY (128 = centre), vendor byte
#define REPORT_LEN 8
extern const uint8_t pad_neutral[REPORT_LEN];

// How far a boot got, kept across a reset for the status read; each transport numbers its own steps.
void pad_stage(uint32_t stage);

void pad_init(void);                             // first thing in app_main
void pad_get_report(uint8_t *out);               // the state to send now
void pad_live_report(const uint8_t *r);          // from the host; ignored while a macro plays
void pad_disconnected(void);                     // the host left: release unless a macro plays
bool pad_playing(void);

// A command from the host (0x10 load, 0x11 data, 0x12 play, 0x13 stop, 0xB0 loader).
// Returns 0, PAD_BAD_LENGTH or PAD_REFUSED.
#define PAD_BAD_LENGTH (-1)
#define PAD_REFUSED (-2)
int pad_command(const uint8_t *buf, size_t len);

// The status record; `mounted` is whether the console has taken the controller. Returns its length.
size_t pad_status(uint8_t *out, size_t cap, bool mounted);

// Provided by the transport: restart into the ROM loader.
void pad_enter_loader(void);
