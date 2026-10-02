/* C6 only: restart when the USB host link stops seeing SOFs, and report the
   registers around the stall after the restart. docs/hardware_esp32.md, Supported boards. */
#pragma once

void usbwatch_start(void);
/* LOG lines for the last stall, if the board restarted because of one. */
void usbwatch_report(void);
