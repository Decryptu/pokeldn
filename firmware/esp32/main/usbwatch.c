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
#include "esp_wifi.h"
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

#ifdef POKELDN_USB_BEACON
/* Diagnostic build only: once a second, the registers and wire counters as a vendor action frame to
   the group address 03:55:53:42:57:00, so a sniffing board records them while USB is dead. */
static void beacon(uint32_t frames)
{
    uint8_t frame[24 + 4 + 4 * (5 + NREGS)] = {0xd0, 0, 0, 0, 0x03, 0x55, 0x53, 0x42, 0x57, 0x00};
    wifi_mode_t mode = WIFI_MODE_NULL;
    if (esp_wifi_get_mode(&mode) != ESP_OK) return;
    const wifi_interface_t ifx = mode == WIFI_MODE_AP ? WIFI_IF_AP : WIFI_IF_STA;
    if (esp_wifi_get_mac(ifx, frame + 10) != ESP_OK) return;
    memcpy(frame + 16, frame + 10, 6);
    memcpy(frame + 24, "\x7f\x02\x55\x53", 4);   /* vendor specific, a local OUI */
    uint32_t *body = (uint32_t *)(frame + 28);
    body[0] = (uint32_t)(esp_timer_get_time() / 1000);
    body[1] = frames;
    body[2] = wire_consumed();
    body[3] = wire_dropped();
    body[4] = s_report.magic == WATCH_MAGIC ? s_report.stalls : 0;
    snap(body + 5);
    esp_wifi_80211_tx(ifx, frame, sizeof(frame), true);
}
#endif

static void watch_task(void *arg)
{
    uint32_t healthy[NREGS];
    int64_t healthy_us = 0, last_change = esp_timer_get_time();
    uint32_t last_frame = *(volatile uint32_t *)USB_SERIAL_JTAG_FRAM_NUM_REG & 0x7ff;
    bool armed = false;   /* a board on a charger never sees a frame: never restart it */
    uint32_t frames = 0, ticks = 0;
    for (;;) {
        const uint32_t frame = *(volatile uint32_t *)USB_SERIAL_JTAG_FRAM_NUM_REG & 0x7ff;
        const int64_t now = esp_timer_get_time();
        if (frame != last_frame) {
            ++frames;
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
#ifdef POKELDN_USB_BEACON
        if (++ticks % 200 == 0) beacon(frames);
#else
        (void)ticks;
#endif
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
    /* A port open resets the chip over USB (reason 11): the report must outlive that. */
    if (esp_reset_reason() == ESP_RST_POWERON) s_report.magic = 0;
    xTaskCreate(watch_task, "usbwatch", 2048, NULL, 2, NULL);
}
#else
void usbwatch_report(void) {}
void usbwatch_start(void) {}
#endif
