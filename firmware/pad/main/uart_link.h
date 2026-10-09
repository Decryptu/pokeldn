// Host frames on UART0 for the classic ESP32 controller board (uart_link.c).
#pragma once
#include <stdbool.h>

// `mounted` answers whether the console holds the controller, for the status record.
void uart_link_start(bool (*mounted)(void));
