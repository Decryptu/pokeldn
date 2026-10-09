idf_build_get_property(idf_target IDF_TARGET)
if(idf_target STREQUAL "esp32s3")
    set(transport "usb_s3.c")
elseif(idf_target STREQUAL "esp32")
    set(transport "bt_esp32.c" "uart_link.c" "pro_report.c")
else()
    message(FATAL_ERROR "the controller firmware needs an ESP32-S3 (USB) or a classic ESP32 (Bluetooth Classic)")
endif()

idf_component_register(SRCS "player.c" ${transport} INCLUDE_DIRS "."
                       PRIV_REQUIRES bt nvs_flash esp_timer esp_app_format esp_driver_gpio esp_driver_uart)
