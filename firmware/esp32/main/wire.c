#include "wire.h"

#include <stdarg.h>
#include <stdatomic.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "driver/uart.h"
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "freertos/task.h"

#define WIRE_UART UART_NUM_0
#define MSG_LOG 0x83

typedef struct {
    uint16_t length;
    uint8_t bytes[];   /* type, payload */
} message_t;

static QueueHandle_t s_out;
static wire_handler_t s_handler;
static atomic_uint s_dropped;
static volatile uint32_t s_pending_baud;

static uint32_t crc32(const uint8_t *p, size_t n)
{
    uint32_t crc = UINT32_MAX;
    while (n--) {
        crc ^= *p++;
        for (int i = 0; i < 8; ++i) crc = (crc >> 1) ^ (0xedb88320U & (0U - (crc & 1)));
    }
    return ~crc;
}

void wire_send(uint8_t type, const void *head, size_t head_len, const void *body, size_t body_len)
{
    const size_t length = 1 + head_len + body_len;
    if (length > WIRE_MAX_PAYLOAD + 1) { atomic_fetch_add(&s_dropped, 1); return; }
    message_t *m = malloc(sizeof(*m) + length);
    if (!m) { atomic_fetch_add(&s_dropped, 1); return; }
    m->length = length;
    m->bytes[0] = type;
    if (head_len) memcpy(m->bytes + 1, head, head_len);
    if (body_len) memcpy(m->bytes + 1 + head_len, body, body_len);
    if (xQueueSend(s_out, &m, 0) != pdTRUE) { free(m); atomic_fetch_add(&s_dropped, 1); }
}

void wire_log(const char *format, ...)
{
    char line[160];
    va_list ap;
    va_start(ap, format);
    int n = vsnprintf(line, sizeof(line), format, ap);
    va_end(ap);
    if (n < 0) return;
    if (n >= (int)sizeof(line)) n = sizeof(line) - 1;
    wire_send(MSG_LOG, line, n, NULL, 0);
}

uint32_t wire_dropped(void) { return atomic_load(&s_dropped); }

/* Applied by the writer after every queued message ahead of it has left at the old rate. */
void wire_set_baud(uint32_t baud) { s_pending_baud = baud; }

static void writer(void *arg)
{
    static uint8_t frame[WIRE_MAX_PAYLOAD + 8], encoded[WIRE_MAX_PAYLOAD + 32];
    for (;;) {
        message_t *m;
        if (xQueueReceive(s_out, &m, portMAX_DELAY) != pdTRUE) continue;
        const size_t n = m->length;
        memcpy(frame, m->bytes, n);
        free(m);
        const uint32_t crc = crc32(frame, n);
        memcpy(frame + n, &crc, 4);
        size_t out = 1, code_at = 0;
        uint8_t code = 1;
        for (size_t i = 0; i < n + 4; ++i) {
            if (!frame[i]) { encoded[code_at] = code; code_at = out++; code = 1; continue; }
            encoded[out++] = frame[i];
            if (++code == 255) { encoded[code_at] = code; code_at = out++; code = 1; }
        }
        encoded[code_at] = code;
        encoded[out++] = 0;
        uart_write_bytes(WIRE_UART, encoded, out);
        if (s_pending_baud && uxQueueMessagesWaiting(s_out) == 0) {
            uart_wait_tx_done(WIRE_UART, pdMS_TO_TICKS(100));
            uart_set_baudrate(WIRE_UART, s_pending_baud);
            s_pending_baud = 0;
        }
    }
}

static void deliver(const uint8_t *encoded, size_t used)
{
    static uint8_t frame[WIRE_MAX_PAYLOAD + 8];
    size_t read = 0, out = 0;
    while (read < used) {
        const uint8_t code = encoded[read++];
        if (!code || read + code - 1 > used || out + code > sizeof(frame)) return;
        for (int i = 1; i < code; ++i) frame[out++] = encoded[read++];
        if (code != 255 && read < used) frame[out++] = 0;
    }
    if (out < 5) return;
    uint32_t crc;
    memcpy(&crc, frame + out - 4, 4);
    if (crc != crc32(frame, out - 4)) return;
    s_handler(frame[0], frame + 1, out - 5);
}

static void reader(void *arg)
{
    static uint8_t chunk[512], encoded[WIRE_MAX_PAYLOAD + 32];
    size_t used = 0;
    bool overflow = false;
    for (;;) {
        const int n = uart_read_bytes(WIRE_UART, chunk, sizeof(chunk), pdMS_TO_TICKS(20));
        for (int i = 0; i < n; ++i) {
            if (chunk[i]) {
                if (used < sizeof(encoded)) encoded[used++] = chunk[i]; else overflow = true;
                continue;
            }
            if (used && !overflow) deliver(encoded, used);
            used = 0;
            overflow = false;
        }
    }
}

void wire_start(wire_handler_t handler)
{
    s_handler = handler;
    const uart_config_t config = {
        .baud_rate = 115200,
        .data_bits = UART_DATA_8_BITS,
        .parity = UART_PARITY_DISABLE,
        .stop_bits = UART_STOP_BITS_1,
        .flow_ctrl = UART_HW_FLOWCTRL_DISABLE,
        .source_clk = UART_SCLK_DEFAULT,
    };
    ESP_ERROR_CHECK(uart_driver_install(WIRE_UART, 16384, 16384, 0, NULL, 0));
    ESP_ERROR_CHECK(uart_param_config(WIRE_UART, &config));
    s_out = xQueueCreate(128, sizeof(message_t *));
    xTaskCreatePinnedToCore(writer, "wire_tx", 4096, NULL, 20, NULL, 1);
    xTaskCreatePinnedToCore(reader, "wire_rx", 6144, NULL, 19, NULL, 1);
}
