// Pro Controller report bytes from the shared state, and the SPI flash a Switch reads; no ESP-IDF here,
// so tests/test_pad_pro.py compiles it on the host (docs/hardware_pad.md, The Bluetooth Classic side).
#include <stdbool.h>
#include "pro_report.h"

// ---- SPI flash the Switch reads (spi_flash_notes) ----

// Factory stick calibration: centre 0x800, 0x700 either way (joycontrol memory.py defaults).
static const uint8_t stick_cal[18] = {0x00, 0x07, 0x70, 0x00, 0x08, 0x80, 0x00, 0x07, 0x70,
                                      0x00, 0x08, 0x80, 0x00, 0x07, 0x70, 0x00, 0x07, 0x70};
static const uint8_t colours[13] = {0x32, 0x32, 0x32, 0xFF, 0xFF, 0xFF, 0x32, 0x32, 0x32,
                                    0x32, 0x32, 0x32, 0xFF};
static const uint8_t imu_cal[24] = {0xD3, 0xFF, 0xD5, 0xFF, 0x55, 0x01, 0x00, 0x40, 0x00, 0x40,
                                    0x00, 0x40, 0x19, 0x00, 0xDD, 0xFF, 0xDC, 0xFF, 0x3B, 0x34,
                                    0x3B, 0x34, 0x3B, 0x34};
static const uint8_t stick_params[18] = {0x0F, 0x30, 0x61, 0x96, 0x30, 0xF3, 0xD4, 0x14, 0x54,
                                         0x41, 0x15, 0x54, 0xC7, 0x79, 0x9C, 0x33, 0x36, 0x63};
static const uint8_t imu_offsets[6] = {0x50, 0xFD, 0x00, 0x00, 0xC6, 0x0F};

uint8_t pro_spi_byte(uint32_t a)
{
    if (a >= 0x6020 && a < 0x6038)
        return imu_cal[a - 0x6020];
    if (a >= 0x603D && a < 0x604F)
        return stick_cal[a - 0x603D];
    if (a >= 0x6050 && a < 0x605D)
        return colours[a - 0x6050];
    if (a >= 0x6080 && a < 0x6086)
        return imu_offsets[a - 0x6080];
    if (a >= 0x6086 && a < 0x6098)
        return stick_params[a - 0x6086];
    if (a >= 0x6098 && a < 0x60AA)
        return stick_params[a - 0x6098];
    return 0xFF; // blank flash: no serial, no user calibration
}

// ---- reports ----

static uint16_t axis(uint8_t v, bool flip)
{
    int d = flip ? 128 - (int)v : (int)v - 128; // the HID report puts up at 0, the Pro report at the top
    int out = 0x800 + d * 0x700 / 128;
    return out < 0 ? 0 : out > 0xFFF ? 0xFFF : out;
}

static void pack_stick(uint8_t *p, uint16_t x, uint16_t y)
{
    p[0] = x & 0xFF;
    p[1] = (x >> 8) | ((y & 0x0F) << 4);
    p[2] = y >> 4;
}

void pro_state(const uint8_t *r, uint8_t timer, uint8_t *p)
{
    uint16_t b = r[0] | r[1] << 8;
    uint8_t hat = r[2];
    bool up = hat == 7 || hat <= 1, right = hat >= 1 && hat <= 3, down = hat >= 3 && hat <= 5,
         left = hat >= 5 && hat <= 7;
    p[0] = timer;
    p[1] = 0x8E; // battery full, Pro Controller, powered
    p[2] = (b & 0x01 ? 0x01 : 0) | (b & 0x08 ? 0x02 : 0) | (b & 0x02 ? 0x04 : 0) | (b & 0x04 ? 0x08 : 0) |
           (b & 0x20 ? 0x40 : 0) | (b & 0x80 ? 0x80 : 0);
    p[3] = (b & 0x100 ? 0x01 : 0) | (b & 0x200 ? 0x02 : 0) | (b & 0x800 ? 0x04 : 0) | (b & 0x400 ? 0x08 : 0) |
           (b & 0x1000 ? 0x10 : 0) | (b & 0x2000 ? 0x20 : 0);
    p[4] = (hat < 8 && down ? 0x01 : 0) | (hat < 8 && up ? 0x02 : 0) | (hat < 8 && right ? 0x04 : 0) |
           (hat < 8 && left ? 0x08 : 0) | (b & 0x10 ? 0x40 : 0) | (b & 0x40 ? 0x80 : 0);
    pack_stick(p + 5, axis(r[3], false), axis(r[4], true));
    pack_stick(p + 8, axis(r[5], false), axis(r[6], true));
    p[11] = 0x80;
}

