// The S3 transport: a wired HORI Pokken pad on its USB port, driven over BLE (docs/hardware_pad.md).
// The Switch accepts this VID/PID as a plain HID gamepad with no Pro Controller handshake.
#include <string.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "driver/gpio.h"
#include "nvs_flash.h"
#include "esp_system.h"
#include "esp_rom_sys.h"
#include "soc/rtc_cntl_reg.h"
#include "tinyusb.h"
#include "tinyusb_default_config.h"
#include "class/hid/hid_device.h"
#include "nimble/nimble_port.h"
#include "nimble/nimble_port_freertos.h"
#include "host/ble_hs.h"
#include "services/gap/ble_svc_gap.h"
#include "services/gatt/ble_svc_gatt.h"

#include "player.h"

#define LED_GPIO 21 // XIAO ESP32S3 user LED, lit while low

// Last BLE step reached, sent in the report's vendor byte for the Mac to read (pad_hid_watch.py):
// 1 synced, 2 advertising, 3 connected; 0x80 | step on an error.
static volatile uint8_t ble_state;

// Boot stages (pad_stage): 1 nvs, 2 usb installed, 3 tasks, 4 nimble init, 5 gatt, 6 host started,
// 7 synced, 8 advertising

// ---- USB ----

static const uint8_t hid_report_desc[] = {
    0x05, 0x01, 0x09, 0x05, 0xA1, 0x01,
    0x15, 0x00, 0x25, 0x01, 0x35, 0x00, 0x45, 0x01, 0x75, 0x01, 0x95, 0x10,
    0x05, 0x09, 0x19, 0x01, 0x29, 0x10, 0x81, 0x02,
    0x05, 0x01, 0x25, 0x07, 0x46, 0x3B, 0x01, 0x75, 0x04, 0x95, 0x01, 0x65, 0x14,
    0x09, 0x39, 0x81, 0x42,
    0x65, 0x00, 0x95, 0x01, 0x81, 0x01,
    0x26, 0xFF, 0x00, 0x46, 0xFF, 0x00, 0x09, 0x30, 0x09, 0x31, 0x09, 0x32, 0x09, 0x35,
    0x75, 0x08, 0x95, 0x04, 0x81, 0x02,
    0x06, 0x00, 0xFF, 0x09, 0x20, 0x95, 0x01, 0x81, 0x02,
    0x0A, 0x21, 0x26, 0x95, 0x08, 0x91, 0x02,
    0xC0,
};

static const tusb_desc_device_t device_desc = {
    .bLength = sizeof(tusb_desc_device_t),
    .bDescriptorType = TUSB_DESC_DEVICE,
    .bcdUSB = 0x0200,
    .bMaxPacketSize0 = CFG_TUD_ENDPOINT0_SIZE,
    .idVendor = 0x0F0D,
    .idProduct = 0x0092,
    .bcdDevice = 0x0100,
    .iManufacturer = 1,
    .iProduct = 2,
    .iSerialNumber = 0,
    .bNumConfigurations = 1,
};

static const char *strings[] = {
    (const char[]){0x09, 0x04},
    "HORI CO.,LTD.",
    "POKKEN CONTROLLER",
};

#define CONFIG_LEN (TUD_CONFIG_DESC_LEN + TUD_HID_INOUT_DESC_LEN)
static const uint8_t config_desc[] = {
    TUD_CONFIG_DESCRIPTOR(1, 1, 0, CONFIG_LEN, 0x80, 500),
    TUD_HID_INOUT_DESCRIPTOR(0, 0, HID_ITF_PROTOCOL_NONE, sizeof(hid_report_desc), 0x02, 0x81, 64, 1),
};

uint8_t const *tud_hid_descriptor_report_cb(uint8_t instance)
{
    return hid_report_desc;
}

uint16_t tud_hid_get_report_cb(uint8_t instance, uint8_t id, hid_report_type_t type, uint8_t *buf, uint16_t len)
{
    return 0;
}

void tud_hid_set_report_cb(uint8_t instance, uint8_t id, hid_report_type_t type, uint8_t const *buf, uint16_t len)
{
}

static void usb_task(void *arg)
{
    uint8_t r[REPORT_LEN];
    for (;;) {
        gpio_set_level(LED_GPIO, tud_mounted() ? 0 : 1);
        if (tud_hid_ready()) {
            pad_get_report(r);
            r[7] = ble_state;
            tud_hid_report(0, r, REPORT_LEN);
        }
        vTaskDelay(1); // one tick is 1 ms at CONFIG_FREERTOS_HZ=1000; 0 would starve NimBLE
    }
}

// ---- BLE ----

// 7a1e0001-5d2c-4c3e-9f4b-504f4b454c44 service, ...0002 report (write), ...0003 status (read)
static const ble_uuid128_t svc_uuid = BLE_UUID128_INIT(
    0x44, 0x4c, 0x45, 0x4b, 0x4f, 0x50, 0x4b, 0x9f, 0x3e, 0x4c, 0x2c, 0x5d, 0x01, 0x00, 0x1e, 0x7a);
static const ble_uuid128_t report_uuid = BLE_UUID128_INIT(
    0x44, 0x4c, 0x45, 0x4b, 0x4f, 0x50, 0x4b, 0x9f, 0x3e, 0x4c, 0x2c, 0x5d, 0x02, 0x00, 0x1e, 0x7a);
static const ble_uuid128_t status_uuid = BLE_UUID128_INIT(
    0x44, 0x4c, 0x45, 0x4b, 0x4f, 0x50, 0x4b, 0x9f, 0x3e, 0x4c, 0x2c, 0x5d, 0x03, 0x00, 0x1e, 0x7a);

static const ble_uuid128_t control_uuid = BLE_UUID128_INIT(
    0x44, 0x4c, 0x45, 0x4b, 0x4f, 0x50, 0x4b, 0x9f, 0x3e, 0x4c, 0x2c, 0x5d, 0x04, 0x00, 0x1e, 0x7a);

static uint8_t own_addr_type;

// The pad owns the USB port, so esptool cannot reset it into the ROM loader; this does.
void pad_enter_loader(void)
{
    nimble_port_stop();
    tinyusb_driver_uninstall();
    // RTC_CNTL_USB_CONF survives the reset: left on USB-OTG, the ROM loader comes up as the
    // flaky OTG CDC device 303a:0009. Give the PHY back to USB Serial/JTAG (303a:1001) first.
    CLEAR_PERI_REG_MASK(RTC_CNTL_USB_CONF_REG, RTC_CNTL_SW_HW_USB_PHY_SEL | RTC_CNTL_SW_USB_PHY_SEL);
    REG_WRITE(RTC_CNTL_OPTION1_REG, RTC_CNTL_FORCE_DOWNLOAD_BOOT);
    esp_rom_software_reset_system();
}

static int control_cb(uint16_t conn, uint16_t attr, struct ble_gatt_access_ctxt *ctxt, void *arg)
{
    static uint8_t buf[512];
    uint16_t len = 0;
    if (ble_hs_mbuf_to_flat(ctxt->om, buf, sizeof(buf), &len) != 0)
        return BLE_ATT_ERR_INVALID_ATTR_VALUE_LEN;
    int rc = pad_command(buf, len);
    return rc == 0 ? 0 : rc == PAD_BAD_LENGTH ? BLE_ATT_ERR_INVALID_ATTR_VALUE_LEN : BLE_ATT_ERR_UNLIKELY;
}
static void advertise(void);

static int access_cb(uint16_t conn, uint16_t attr, struct ble_gatt_access_ctxt *ctxt, void *arg)
{
    if (ctxt->op == BLE_GATT_ACCESS_OP_WRITE_CHR) {
        uint8_t r[REPORT_LEN];
        uint16_t len = 0;
        if (OS_MBUF_PKTLEN(ctxt->om) != REPORT_LEN)
            return BLE_ATT_ERR_INVALID_ATTR_VALUE_LEN;
        ble_hs_mbuf_to_flat(ctxt->om, r, REPORT_LEN, &len);
        pad_live_report(r);
        return 0;
    }
    if (ctxt->op == BLE_GATT_ACCESS_OP_READ_CHR) {
        uint8_t s[64];
        size_t n = pad_status(s, sizeof(s), tud_mounted());
        return os_mbuf_append(ctxt->om, s, n) == 0 ? 0 : BLE_ATT_ERR_INSUFFICIENT_RES;
    }
    return BLE_ATT_ERR_UNLIKELY;
}

static const struct ble_gatt_svc_def services[] = {
    {
        .type = BLE_GATT_SVC_TYPE_PRIMARY,
        .uuid = &svc_uuid.u,
        .characteristics = (struct ble_gatt_chr_def[]){
            {.uuid = &report_uuid.u, .access_cb = access_cb,
             .flags = BLE_GATT_CHR_F_WRITE | BLE_GATT_CHR_F_WRITE_NO_RSP},
            {.uuid = &status_uuid.u, .access_cb = access_cb, .flags = BLE_GATT_CHR_F_READ},
            {.uuid = &control_uuid.u, .access_cb = control_cb, .flags = BLE_GATT_CHR_F_WRITE},
            {0},
        },
    },
    {0},
};

static int gap_event(struct ble_gap_event *event, void *arg)
{
    switch (event->type) {
    case BLE_GAP_EVENT_CONNECT:
        ble_state = 3;
        if (event->connect.status != 0)
            advertise();
        break;
    case BLE_GAP_EVENT_DISCONNECT:
        pad_disconnected();
        advertise();
        break;
    case BLE_GAP_EVENT_ADV_COMPLETE:
        advertise();
        break;
    }
    return 0;
}

static void advertise(void)
{
    struct ble_hs_adv_fields fields = {0};
    const char *name = ble_svc_gap_device_name();
    fields.flags = BLE_HS_ADV_F_DISC_GEN | BLE_HS_ADV_F_BREDR_UNSUP;
    fields.name = (uint8_t *)name;
    fields.name_len = strlen(name);
    fields.name_is_complete = 1;
    if (ble_gap_adv_set_fields(&fields) != 0) {
        ble_state = 0x82;
        return;
    }
    struct ble_gap_adv_params params = {.conn_mode = BLE_GAP_CONN_MODE_UND, .disc_mode = BLE_GAP_DISC_MODE_GEN};
    ble_state = ble_gap_adv_start(own_addr_type, NULL, BLE_HS_FOREVER, &params, gap_event, NULL) == 0 ? 2 : 0x83;
    if (ble_state == 2)
        pad_stage(8);
}

static void on_sync(void)
{
    ble_state = 1;
    pad_stage(7);
    if (ble_hs_id_infer_auto(0, &own_addr_type) != 0) {
        ble_state = 0x81;
        return;
    }
    advertise();
}

static void host_task(void *param)
{
    nimble_port_run();
    nimble_port_freertos_deinit();
}

void app_main(void)
{
    pad_init();
    gpio_reset_pin(LED_GPIO);
    gpio_set_direction(LED_GPIO, GPIO_MODE_OUTPUT);
    gpio_set_level(LED_GPIO, 1);

    esp_err_t err = nvs_flash_init();
    if (err == ESP_ERR_NVS_NO_FREE_PAGES || err == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        nvs_flash_erase();
        nvs_flash_init();
    }
    pad_stage(1);

    tinyusb_config_t tusb_cfg = TINYUSB_DEFAULT_CONFIG();
    tusb_cfg.descriptor.device = &device_desc;
    tusb_cfg.descriptor.string = strings;
    tusb_cfg.descriptor.string_count = sizeof(strings) / sizeof(strings[0]);
    tusb_cfg.descriptor.full_speed_config = config_desc;
    ESP_ERROR_CHECK(tinyusb_driver_install(&tusb_cfg));
    pad_stage(2);
    xTaskCreate(usb_task, "pad_usb", 3072, NULL, 3, NULL);
    pad_stage(3);

    ESP_ERROR_CHECK(nimble_port_init());
    pad_stage(4);
    ble_hs_cfg.sync_cb = on_sync;
    ble_svc_gap_init();
    ble_svc_gatt_init();
    ble_gatts_count_cfg(services);
    ble_gatts_add_svcs(services);
    ble_svc_gap_device_name_set("POKELDN-PAD");
    pad_stage(5);
    nimble_port_freertos_init(host_task);
    pad_stage(6);
}
