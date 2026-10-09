// Pure Pro Controller encoding (pro_report.c).
#pragma once
#include <stdint.h>

// The first 12 bytes of a 0x21 or 0x30 payload: timer, battery, buttons, sticks, vibrator, from an
// 8-byte HORI-format state (player.h).
void pro_state(const uint8_t *hori, uint8_t timer, uint8_t *out);

// One byte of the SPI flash the Switch reads: calibration, colours; 0xFF elsewhere.
uint8_t pro_spi_byte(uint32_t address);
