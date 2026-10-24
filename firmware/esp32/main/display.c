#include <stdlib.h>
#include <string.h>

#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "freertos/task.h"

#include "display.h"
#include "panel.h"
#include "screen.h"

#define FRAME_MS 50

typedef struct {
    uint16_t length;       /* 0: reset */
    uint8_t *payload;
} display_msg_t;

static QueueHandle_t s_commands;
static display_state_t s_state;
static uint8_t s_frame[SCREEN_BYTES];
static uint8_t s_power = SCENE_ON;   /* each panel_init's */

static void display_task(void *arg)
{
    TickType_t wake = xTaskGetTickCount();
    for (;;) {
        const uint32_t now = (uint32_t)(esp_timer_get_time() / 1000);
        display_msg_t msg;
        while (xQueueReceive(s_commands, &msg, 0) == pdTRUE) {
            if (msg.length) scene_command(msg.payload, msg.length, now);
            else scene_reset();
            free(msg.payload);
        }
        scene_radio_t state = {0};
        if (s_state) s_state(&state);
        const uint8_t power = scene_draw(s_frame, &state, now);
        /* The frame goes before the panel lights, so waking never shows the last one. */
        if (power != SCENE_OFF) panel_present(s_frame);
        if (power != s_power && panel_power(power))
            s_power = power;
        vTaskDelayUntil(&wake, pdMS_TO_TICKS(FRAME_MS));
    }
}

bool display_start(display_state_t state)
{
    if (!panel_init()) return false;
    s_state = state;
    s_commands = xQueueCreate(8, sizeof(display_msg_t));
    xTaskCreatePinnedToCore(display_task, "display", 3072, NULL, 1, NULL, configNUMBER_OF_CORES - 1);
    return true;
}

/* Copied and queued: the wire's reader never waits on a frame being drawn. */
bool display_command(const uint8_t *payload, size_t length)
{
    if (!s_commands || !length || length > 1024) return false;
    display_msg_t msg = {.length = (uint16_t)length, .payload = malloc(length)};
    if (!msg.payload) return false;
    memcpy(msg.payload, payload, length);
    if (xQueueSend(s_commands, &msg, 0) == pdTRUE) return true;
    free(msg.payload);
    return false;
}

void display_reset(void)
{
    const display_msg_t msg = {0};
    if (s_commands) xQueueSend(s_commands, &msg, 0);
}
