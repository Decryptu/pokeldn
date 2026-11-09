/* The LCKFB szpi ESP32-S3 board's shared parts: the I2C bus on GPIO1/2 and its PCA9557 expander, which
   holds the LCD's CS, the speaker amplifier's enable and the camera's power-down.
   [xiaozhi-esp32 boards/lckfb/szpi-esp32s3] docs/hardware_esp32.md, The szpi board. */
#pragma once

#include <stdbool.h>

#include "driver/i2c_master.h"

/* Once: the bus, then the expander with the LCD selected, the amplifier off and the camera powered down. */
bool board_szpi_start(void);
i2c_master_bus_handle_t board_szpi_bus(void);
bool board_szpi_amplifier(bool on);
