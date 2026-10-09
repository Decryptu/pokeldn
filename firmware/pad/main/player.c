// The controller state and the macro player (docs/hardware_pad.md, The Bluetooth side).
#include <string.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "esp_app_desc.h"
#include "esp_attr.h"
#include "esp_system.h"
#include "player.h"

const uint8_t pad_neutral[REPORT_LEN] = {0, 0, 8, 128, 128, 128, 128, 0};
static uint8_t report[REPORT_LEN];
static portMUX_TYPE report_lock = portMUX_INITIALIZER_UNLOCKED;
static uint32_t writes;

// A macro: entries [0, loop_start) once, then [loop_start, count) `loops` times (0 = until
// stopped). Each entry is a report and how long it is held.
#define MAX_ENTRIES 8192
#define ENTRY_LEN (REPORT_LEN + 2)
static uint8_t program[MAX_ENTRIES][ENTRY_LEN];
static uint16_t program_count, loop_start;
static uint32_t loops;
static volatile bool playing;
static volatile uint32_t loops_done;
static volatile uint16_t play_index;
static TaskHandle_t player;

RTC_NOINIT_ATTR static uint32_t stage_now, boots;
static uint8_t stage_before;

enum { CMD_LOAD = 0x10, CMD_DATA = 0x11, CMD_PLAY = 0x12, CMD_STOP = 0x13, CMD_DOWNLOAD = 0xB0 };

static void set_report(const uint8_t *r)
{
    taskENTER_CRITICAL(&report_lock);
    memcpy(report, r, REPORT_LEN);
    taskEXIT_CRITICAL(&report_lock);
}

void pad_get_report(uint8_t *out)
{
    taskENTER_CRITICAL(&report_lock);
    memcpy(out, report, REPORT_LEN);
    taskEXIT_CRITICAL(&report_lock);
}

void pad_stage(uint32_t stage)
{
    stage_now = stage;
}

bool pad_playing(void)
{
    return playing;
}

void pad_live_report(const uint8_t *r)
{
    if (!playing) // a running macro owns the report until it ends or is stopped
        set_report(r);
    writes++;
}

void pad_disconnected(void)
{
    // A host that vanishes must not leave a button held; a macro keeps running.
    if (!playing)
        set_report(pad_neutral);
}

static void player_task(void *arg)
{
    for (;;) {
        ulTaskNotifyTake(pdTRUE, portMAX_DELAY);
        TickType_t wake = xTaskGetTickCount();
        uint16_t i = 0;
        loops_done = 0;
        while (playing && program_count) {
            if (i == program_count) {
                loops_done++;
                if (loops && loops_done >= loops)
                    break;
                i = loop_start;
                if (i >= program_count)
                    break;
            }
            play_index = i;
            set_report(program[i]);
            uint16_t ms = program[i][REPORT_LEN] | program[i][REPORT_LEN + 1] << 8;
            if (ms)
                vTaskDelayUntil(&wake, pdMS_TO_TICKS(ms));
            i++;
        }
        playing = false;
        set_report(pad_neutral);
    }
}

static void stop_playing(void)
{
    playing = false;
    for (int n = 0; n < 50 && eTaskGetState(player) != eBlocked; n++)
        vTaskDelay(1);
}

static void loader_task(void *arg)
{
    vTaskDelay(pdMS_TO_TICKS(200)); // the host's write is answered first
    pad_enter_loader();
}

int pad_command(const uint8_t *buf, size_t len)
{
    if (len == 0)
        return PAD_BAD_LENGTH;
    switch (buf[0]) {
    case CMD_LOAD: // u16 count, u16 loop_start, u32 loops
        if (len != 9)
            return PAD_BAD_LENGTH;
        stop_playing();
        program_count = buf[1] | buf[2] << 8;
        loop_start = buf[3] | buf[4] << 8;
        memcpy(&loops, buf + 5, 4);
        if (program_count > MAX_ENTRIES || loop_start > program_count) {
            program_count = 0;
            return PAD_REFUSED;
        }
        return 0;
    case CMD_DATA: { // u16 first index, then entries
        if (len < 3 || (len - 3) % ENTRY_LEN)
            return PAD_BAD_LENGTH;
        uint16_t first = buf[1] | buf[2] << 8;
        size_t n = (len - 3) / ENTRY_LEN;
        if (first + n > program_count)
            return PAD_BAD_LENGTH;
        if (playing)
            return PAD_REFUSED;
        memcpy(program[first], buf + 3, n * ENTRY_LEN);
        return 0;
    }
    case CMD_PLAY:
        stop_playing();
        playing = true;
        xTaskNotifyGive(player);
        return 0;
    case CMD_STOP:
        stop_playing();
        set_report(pad_neutral);
        return 0;
    case CMD_DOWNLOAD:
        xTaskCreate(loader_task, "pad_dl", 3072, NULL, 1, NULL);
        return 0;
    }
    return PAD_REFUSED;
}

size_t pad_status(uint8_t *s, size_t cap, bool mounted)
{
    // mounted u8, writes u32, playing u8, loops done u32, index u16, count u16, version text,
    // NUL, reset reason u8, previous boot's last stage u8, boots u16
    const char *ver = esp_app_get_description()->version;
    size_t vlen = strnlen(ver, 28);
    if (cap < 14 + vlen + 5)
        return 0;
    uint32_t done = loops_done;
    uint16_t index = play_index, b = boots;
    s[0] = mounted;
    memcpy(s + 1, &writes, 4);
    s[5] = playing;
    memcpy(s + 6, &done, 4);
    memcpy(s + 10, &index, 2);
    memcpy(s + 12, &program_count, 2);
    memcpy(s + 14, ver, vlen);
    uint8_t *d = s + 14 + vlen;
    d[0] = 0;
    d[1] = esp_reset_reason();
    d[2] = stage_before;
    memcpy(d + 3, &b, 2);
    return 14 + vlen + 5;
}

void pad_init(void)
{
    if (esp_reset_reason() == ESP_RST_POWERON)
        stage_now = boots = 0;
    stage_before = stage_now;
    stage_now = 0;
    boots++;
    set_report(pad_neutral);
    xTaskCreate(player_task, "pad_play", 3072, NULL, 6, &player);
}
