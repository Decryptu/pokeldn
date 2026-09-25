/* The host link: COBS frames on UART0, each `type | payload | crc32-le`, closed by 0x00.
   The message set is in docs/hardware_esp32.md and pokeldn/ldn/esp32.py. */
#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#define WIRE_MAX_PAYLOAD 1600

typedef void (*wire_handler_t)(uint8_t type, const uint8_t *payload, size_t length);

void wire_start(wire_handler_t handler);
/* Queues one message; safe from any task and from Wi-Fi callbacks. Drops (and counts) when the
   queue is full rather than blocking the caller. */
void wire_send(uint8_t type, const void *head, size_t head_len, const void *body, size_t body_len);
/* The same, waiting up to `ticks` for room in the queue; false if there was none. */
bool wire_send_wait(uint8_t type, const void *head, size_t head_len, const void *body,
                    size_t body_len, uint32_t ticks);
void wire_log(const char *format, ...) __attribute__((format(printf, 1, 2)));
void wire_set_baud(uint32_t baud);
/* Restarts the count of host bytes read that CREDIT (0x8B, u32) reports; called on HELLO, from the
   handler, so the count starts after the HELLO frame on both sides. */
void wire_credit_reset(void);
uint32_t wire_dropped(void);
/* Host commands lost: frames that failed COBS or their CRC; the 128-byte hardware FIFO
   overflowing before the driver drained it; the driver's 16 KB ring full. */
uint32_t wire_rx_bad(void);
uint32_t wire_rx_fifo_ovf(void);
uint32_t wire_rx_buffer_full(void);
