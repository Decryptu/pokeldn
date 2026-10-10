// The host link of a classic ESP32 controller board: frames on UART0, which the board's USB-to-serial
// chip carries to the computer (pokeldn/pad/serial_link.py, docs/hardware_pad.md, The serial side).
#include <string.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "driver/uart.h"
#include "player.h"
#include "uart_link.h"

#define PORT UART_NUM_0
#define BAUD 921600
#define MAX_BODY 600

enum { REPORT = 0x01, STATUS = 0x02, COMMAND = 0x03, RESULT = 0x81, STATUS_REPLY = 0x82 };

static bool (*mounted_fn)(void);

static void send_frame(uint8_t kind, const uint8_t *payload, size_t len)
{
    uint8_t head[5] = {0xA5, 0x5A, (uint8_t)(len + 1), (uint8_t)((len + 1) >> 8), kind};
    uint8_t sum = kind;
    for (size_t i = 0; i < len; i++)
        sum += payload[i];
    uart_write_bytes(PORT, head, sizeof(head));
    if (len)
        uart_write_bytes(PORT, payload, len);
    uart_write_bytes(PORT, &sum, 1);
}

static void reply(int8_t rc)
{
    send_frame(RESULT, (const uint8_t *)&rc, 1);
}

static void handle(uint8_t kind, const uint8_t *p, size_t len)
{
    if (kind == REPORT) {
        if (len != REPORT_LEN) {
            reply(PAD_BAD_LENGTH);
            return;
        }
        pad_live_report(p);
        reply(0);
    } else if (kind == STATUS) {
        uint8_t s[64];
        size_t n = pad_status(s, sizeof(s), mounted_fn && mounted_fn());
        send_frame(STATUS_REPLY, s, n);
    } else if (kind == COMMAND) {
        reply((int8_t)pad_command(p, len));
    }
}

static void uart_task(void *arg)
{
    static uint8_t body[MAX_BODY];
    uint8_t c, head[4];
    for (;;) {
        // A5 5A, length u16, body, sum; anything else (a host probing another protocol) is skipped.
        if (uart_read_bytes(PORT, &c, 1, portMAX_DELAY) != 1 || c != 0xA5)
            continue;
        if (uart_read_bytes(PORT, &c, 1, pdMS_TO_TICKS(50)) != 1 || c != 0x5A)
            continue;
        if (uart_read_bytes(PORT, head, 2, pdMS_TO_TICKS(50)) != 2)
            continue;
        size_t len = head[0] | head[1] << 8;
        if (len < 1 || len > MAX_BODY)
            continue;
        if (uart_read_bytes(PORT, body, len, pdMS_TO_TICKS(200)) != (int)len)
            continue;
        uint8_t sum = 0, check;
        for (size_t i = 0; i < len; i++)
            sum += body[i];
        if (uart_read_bytes(PORT, &check, 1, pdMS_TO_TICKS(50)) != 1 || check != sum)
            continue;
        handle(body[0], body + 1, len - 1);
    }
}

void uart_link_start(bool (*mounted)(void))
{
    mounted_fn = mounted;
    uart_config_t cfg = {
        .baud_rate = BAUD,
        .data_bits = UART_DATA_8_BITS,
        .parity = UART_PARITY_DISABLE,
        .stop_bits = UART_STOP_BITS_1,
        .flow_ctrl = UART_HW_FLOWCTRL_DISABLE,
        .source_clk = UART_SCLK_DEFAULT,
    };
    uart_driver_install(PORT, 2048, 2048, 0, NULL, 0);
    uart_param_config(PORT, &cfg);
    // With CONFIG_ESP_CONSOLE_NONE nothing routes UART0 to GPIO1/3; without this the board never answers.
    uart_set_pin(PORT, 1, 3, UART_PIN_NO_CHANGE, UART_PIN_NO_CHANGE);
    xTaskCreate(uart_task, "pad_uart", 4096, NULL, 5, NULL);
}
