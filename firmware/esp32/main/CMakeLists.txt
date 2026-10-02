idf_build_get_property(idf_target IDF_TARGET)
if(idf_target STREQUAL "esp32s3" OR idf_target STREQUAL "esp32c3" OR idf_target STREQUAL "esp32c6")
    set(wire_driver esp_driver_usb_serial_jtag)
elseif(idf_target STREQUAL "esp32")
    set(wire_driver esp_driver_uart)
else()
    message(FATAL_ERROR "pokeldn supports esp32, esp32s3, esp32c3 and esp32c6 targets only")
endif()

idf_component_register(
    SRCS "radio.c" "wire.c" "led.c"
    INCLUDE_DIRS "."
    PRIV_REQUIRES esp_app_format esp_wifi wpa_supplicant ${wire_driver} esp_driver_ledc esp_driver_gpio esp_timer nvs_flash esp_event)
