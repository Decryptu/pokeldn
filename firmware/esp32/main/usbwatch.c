/* C6 USB watch: a XIAO ESP32C6's USB Serial/JTAG device went deaf twice as a console left a trade
   while the firmware ran on. Samples the SOF frame number every 5 ms; once frames have counted and
   then stop for 2 s, keeps the registers from before and after in RTC memory, restarts, and reports
   them as LOG lines on the next HELLO. docs/hardware_esp32.md, Supported boards. */
#include "usbwatch.h"

#include "sdkconfig.h"

#if CONFIG_IDF_TARGET_ESP32C6
#include <stdbool.h>
#include <string.h>

#include "esp_attr.h"
#include "esp_system.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "soc/io_mux_reg.h"
#include "soc/pcr_reg.h"
#include "soc/usb_serial_jtag_reg.h"

#include "wire.h"

#define WATCH_MAGIC 0x55534257u
#define STALL_US 2000000

static const uint32_t REGS[] = {
    USB_SERIAL_JTAG_CONF0_REG, USB_SERIAL_JTAG_FRAM_NUM_REG, USB_SERIAL_JTAG_INT_RAW_REG,
    USB_SERIAL_JTAG_INT_ENA_REG, USB_SERIAL_JTAG_MISC_CONF_REG, USB_SERIAL_JTAG_MEM_CONF_REG,
    USB_SERIAL_JTAG_CHIP_RST_REG, USB_SERIAL_JTAG_BUS_RESET_ST_REG, USB_SERIAL_JTAG_IN_EP1_ST_REG,
    USB_SERIAL_JTAG_OUT_EP1_ST_REG, PCR_USB_DEVICE_CONF_REG, PCR_SYSCLK_CONF_REG,
    PCR_CPU_FREQ_CONF_REG, PCR_PLL_DIV_CLK_EN_REG, IO_MUX_GPIO12_REG, IO_MUX_GPIO13_REG,
};
#define NREGS (sizeof(REGS) / sizeof(REGS[0]))

typedef struct {
    uint32_t magic, stalls;
    int64_t healthy_us, stalled_us;
    uint32_t healthy[NREGS], stalled[NREGS];
} report_t;

static RTC_NOINIT_ATTR report_t s_report;

static void snap(uint32_t *out)
{
    for (size_t i = 0; i < NREGS; ++i) out[i] = *(volatile uint32_t *)REGS[i];
}

static void watch_task(void *arg)
{
    uint32_t healthy[NREGS];
    int64_t healthy_us = 0, last_change = esp_timer_get_time();
    uint32_t last_frame = *(volatile uint32_t *)USB_SERIAL_JTAG_FRAM_NUM_REG & 0x7ff;
    bool armed = false;   /* a board on a charger never sees a frame: never restart it */
    for (;;) {
        const uint32_t frame = *(volatile uint32_t *)USB_SERIAL_JTAG_FRAM_NUM_REG & 0x7ff;
        const int64_t now = esp_timer_get_time();
        if (frame != last_frame) {
            armed = true;
            last_frame = frame;
            last_change = now;
            snap(healthy);
            healthy_us = now;
        } else if (armed && now - last_change > STALL_US) {
            s_report.stalls = s_report.magic == WATCH_MAGIC ? s_report.stalls + 1 : 1;
            s_report.healthy_us = healthy_us;
            s_report.stalled_us = now;
            memcpy(s_report.healthy, healthy, sizeof(healthy));
            snap(s_report.stalled);
            s_report.magic = WATCH_MAGIC;
            esp_restart();
        }
        vTaskDelay(pdMS_TO_TICKS(5));
    }
}

void usbwatch_report(void)
{
    wire_log("usbwatch: reset reason %d, up %lld ms", (int)esp_reset_reason(), esp_timer_get_time() / 1000);
    if (s_report.magic != WATCH_MAGIC) return;
    wire_log("usbwatch: restart %lu after a SOF stall; healthy at %lld us, stalled at %lld us",
             (unsigned long)s_report.stalls, s_report.healthy_us, s_report.stalled_us);
    for (size_t i = 0; i < NREGS; ++i)
        wire_log("usbwatch: %08lx healthy %08lx stalled %08lx", (unsigned long)REGS[i],
                 (unsigned long)s_report.healthy[i], (unsigned long)s_report.stalled[i]);
}

void usbwatch_start(void)
{
    if (esp_reset_reason() != ESP_RST_SW) s_report.magic = 0;
    xTaskCreate(watch_task, "usbwatch", 2048, NULL, 2, NULL);
}
#else
void usbwatch_report(void) {}
void usbwatch_start(void) {}
#endif
