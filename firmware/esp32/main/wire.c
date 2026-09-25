#include "wire.h"

#include <stdarg.h>
#include <stdatomic.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "driver/uart.h"
#include "esp_system.h"
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "freertos/task.h"

#define WIRE_UART UART_NUM_0
#define MSG_LOG 0x83
#define MSG_CREDIT 0x8B
/* A CREDIT goes out every CREDIT_STEP bytes read, and when the line falls idle. The host keeps
   under half the 16 KB RX ring in flight, so a command waiting on a full Wi-Fi queue stalls the
   host and never overflows the ring. docs/hardware_esp32.md, The serial ceiling. */
#define CREDIT_STEP 1024

typedef struct {
    uint16_t length;
    uint8_t bytes[];   /* type, payload */
} message_t;

/* The queue drops on memory, not on count: 128 entries filled at 96 KB of free heap during a
   Scarlet burst and dropped 337 messages. The floor keeps room for the driver's RX buffers.
   docs/hardware_esp32.md, The serial ceiling. */
#define WIRE_QUEUE_LENGTH 384
#define WIRE_HEAP_FLOOR (64 * 1024)

static QueueHandle_t s_out, s_uart_events;
static wire_handler_t s_handler;
static atomic_uint s_dropped, s_rx_bad, s_rx_fifo_ovf, s_rx_buffer_full;
static uint32_t s_consumed, s_credited;   /* the reader task's own; the handler runs on it */

static uint32_t crc32(const uint8_t *p, size_t n)
{
    uint32_t crc = UINT32_MAX;
    while (n--) {
        crc ^= *p++;
        for (int i = 0; i < 8; ++i) crc = (crc >> 1) ^ (0xedb88320U & (0U - (crc & 1)));
    }
    return ~crc;
}

bool wire_send_wait(uint8_t type, const void *head, size_t head_len, const void *body,
                    size_t body_len, uint32_t ticks)
{
    const size_t length = 1 + head_len + body_len;
    if (length > WIRE_MAX_PAYLOAD + 1) return false;
    if (esp_get_free_heap_size() < WIRE_HEAP_FLOOR + length) return false;
    message_t *m = malloc(sizeof(*m) + length);
    if (!m) return false;
    m->length = length;
    m->bytes[0] = type;
    if (head_len) memcpy(m->bytes + 1, head, head_len);
    if (body_len) memcpy(m->bytes + 1 + head_len, body, body_len);
    if (xQueueSend(s_out, &m, ticks) != pdTRUE) { free(m); return false; }
    return true;
}

void wire_send(uint8_t type, const void *head, size_t head_len, const void *body, size_t body_len)
{
    if (!wire_send_wait(type, head, head_len, body, body_len, 0)) atomic_fetch_add(&s_dropped, 1);
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
uint32_t wire_rx_bad(void) { return atomic_load(&s_rx_bad); }
uint32_t wire_rx_fifo_ovf(void) { return atomic_load(&s_rx_fifo_ovf); }
uint32_t wire_rx_buffer_full(void) { return atomic_load(&s_rx_buffer_full); }

static void send_credit(void)
{
    s_credited = s_consumed;
    wire_send(MSG_CREDIT, &s_credited, 4, NULL, 0);
}

/* A CREDIT of 0 at once, so the host's window is shut from the first byte after the HELLO. */
void wire_credit_reset(void)
{
    s_consumed = 0;
    send_credit();
}

/* A zero-length queue entry carrying the rate: the writer switches when it reaches it, so every
   message queued before it (the BAUD RESULT above all) leaves at the old rate. A flag checked on
   an empty queue raced the RESULT while RX_MGMT kept the writer busy. */
void wire_set_baud(uint32_t baud)
{
    message_t *m = malloc(sizeof(*m) + 4);
    if (!m) return;
    m->length = 0;
    memcpy(m->bytes, &baud, 4);
    if (xQueueSend(s_out, &m, portMAX_DELAY) != pdTRUE) free(m);
}

static void writer(void *arg)
{
    static uint8_t frame[WIRE_MAX_PAYLOAD + 8], encoded[WIRE_MAX_PAYLOAD + 32];
    for (;;) {
        message_t *m;
        if (xQueueReceive(s_out, &m, portMAX_DELAY) != pdTRUE) continue;
        const size_t n = m->length;
        if (!n) {
            uint32_t baud;
            memcpy(&baud, m->bytes, 4);
            free(m);
            /* The 16 KB TX ring can hold a second and more at 115200; a 100 ms wait switched
               the rate with the RESULT still in it. */
            uart_wait_tx_done(WIRE_UART, pdMS_TO_TICKS(3000));
            uart_set_baudrate(WIRE_UART, baud);
            continue;
        }
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
    }
}

/* A frame that fails here is a command lost between host and board; wire_rx_bad counts them. */
static void deliver(const uint8_t *encoded, size_t used)
{
    static uint8_t frame[WIRE_MAX_PAYLOAD + 8];
    size_t read = 0, out = 0;
    while (read < used) {
        const uint8_t code = encoded[read++];
        if (!code || read + code - 1 > used || out + code > sizeof(frame)) {
            atomic_fetch_add(&s_rx_bad, 1);
            return;
        }
        for (int i = 1; i < code; ++i) frame[out++] = encoded[read++];
        if (code != 255 && read < used) frame[out++] = 0;
    }
    uint32_t crc;
    if (out < 5 || (memcpy(&crc, frame + out - 4, 4), crc != crc32(frame, out - 4))) {
        atomic_fetch_add(&s_rx_bad, 1);
        return;
    }
    s_handler(frame[0], frame + 1, out - 5);
}

/* The UART driver is installed here, on core 1, because its interrupt is allocated on the core
   that installs it. On core 0, with the Wi-Fi task, a console's receive flood lost 500 host
   commands in 7 s and none after. docs/hardware_esp32.md, The serial ceiling. */
static void reader(void *arg)
{
    const uart_config_t config = {
        .baud_rate = 115200,
        .data_bits = UART_DATA_8_BITS,
        .parity = UART_PARITY_DISABLE,
        .stop_bits = UART_STOP_BITS_1,
        .flow_ctrl = UART_HW_FLOWCTRL_DISABLE,
        .source_clk = UART_SCLK_DEFAULT,
    };
    /* 64 events: a queue that fills with UART_DATA drops the overflow events that count a loss. */
    ESP_ERROR_CHECK(uart_driver_install(WIRE_UART, 16384, 16384, 64, &s_uart_events, 0));
    ESP_ERROR_CHECK(uart_param_config(WIRE_UART, &config));
    /* With CONFIG_ESP_CONSOLE_NONE nothing routes UART0 to GPIO1/3; the board stays mute without this. */
    ESP_ERROR_CHECK(uart_set_pin(WIRE_UART, 1, 3, UART_PIN_NO_CHANGE, UART_PIN_NO_CHANGE));
    xTaskCreatePinnedToCore(writer, "wire_tx", 4096, NULL, 20, NULL, 1);
    static uint8_t chunk[512], encoded[WIRE_MAX_PAYLOAD + 32];
    size_t used = 0;
    bool overflow = false;
    for (;;) {
        uart_event_t event;
        while (xQueueReceive(s_uart_events, &event, 0) == pdTRUE) {
            if (event.type == UART_FIFO_OVF) atomic_fetch_add(&s_rx_fifo_ovf, 1);
            else if (event.type == UART_BUFFER_FULL) atomic_fetch_add(&s_rx_buffer_full, 1);
        }
        const int n = uart_read_bytes(WIRE_UART, chunk, sizeof(chunk), pdMS_TO_TICKS(20));
        if (n <= 0 && s_consumed != s_credited) send_credit();
        for (int i = 0; i < n; ++i) {
            ++s_consumed;   /* before the handler, so a HELLO's reset excludes its own delimiter */
            if (chunk[i]) {
                if (used < sizeof(encoded)) encoded[used++] = chunk[i]; else overflow = true;
                continue;
            }
            if (used && overflow) atomic_fetch_add(&s_rx_bad, 1);
            if (used && !overflow) deliver(encoded, used);
            used = 0;
            overflow = false;
        }
        if (s_consumed - s_credited >= CREDIT_STEP) send_credit();
    }
}

void wire_start(wire_handler_t handler)
{
    s_handler = handler;
    s_out = xQueueCreate(WIRE_QUEUE_LENGTH, sizeof(message_t *));
    xTaskCreatePinnedToCore(reader, "wire_rx", 6144, NULL, 19, NULL, 1);
}
