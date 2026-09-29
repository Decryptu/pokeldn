# The ESP32-S3 has no USB-UART bridge on a native-USB board: its host link is the chip's USB Serial/JTAG.
idf_build_get_property(idf_target IDF_TARGET)
if(idf_target STREQUAL "esp32s3")
    set(wire_driver esp_driver_usb_serial_jtag)
else()
    set(wire_driver esp_driver_uart)
endif()

idf_component_register(
    SRCS "radio.c" "wire.c" "led.c"
    INCLUDE_DIRS "."
    PRIV_REQUIRES esp_wifi wpa_supplicant ${wire_driver} esp_driver_ledc esp_driver_gpio esp_timer nvs_flash esp_event)
