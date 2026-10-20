idf_build_get_property(idf_target IDF_TARGET)
if(idf_target STREQUAL "esp32s3" OR idf_target STREQUAL "esp32c3" OR idf_target STREQUAL "esp32c6")
    set(wire_driver esp_driver_usb_serial_jtag)
elseif(idf_target STREQUAL "esp32")
    set(wire_driver esp_driver_uart)
else()
    message(FATAL_ERROR "pokeldn supports esp32, esp32s3, esp32c3 and esp32c6 targets only")
endif()

# The screen's panel, POKELDN_DISPLAY in the environment of idf.py: OLED (the default, an SSD1306 on
# I2C, probed) or E32R40T (that board's ST7796S, classic ESP32). docs/hardware_esp32.md, The screen.
set(POKELDN_DISPLAY "$ENV{POKELDN_DISPLAY}")
if(NOT POKELDN_DISPLAY)
    set(POKELDN_DISPLAY OLED)
endif()
if(POKELDN_DISPLAY STREQUAL "E32R40T" AND idf_target STREQUAL "esp32")
    set(panel_source "panel_e32r40t.c")
    set(panel_driver esp_driver_spi)
elseif(POKELDN_DISPLAY STREQUAL "OLED")
    set(panel_source "panel_oled.c")
    set(panel_driver esp_driver_i2c)
else()
    message(FATAL_ERROR "POKELDN_DISPLAY=${POKELDN_DISPLAY}: OLED, or E32R40T on the esp32 target")
endif()

if(DEFINED ENV{POKELDN_BLE})
    set(ble_component bt)
endif()

idf_component_register(
    SRCS "radio.c" "ble.c" "wire.c" "led.c" "usbwatch.c" "display.c" ${panel_source} "scene.c" "screen.c"
    INCLUDE_DIRS "."
    PRIV_REQUIRES esp_app_format esp_wifi wpa_supplicant ${wire_driver} esp_driver_ledc esp_driver_gpio ${panel_driver} esp_timer nvs_flash esp_event ${ble_component})

target_compile_definitions(${COMPONENT_LIB} PRIVATE POKELDN_DISPLAY_${POKELDN_DISPLAY}
                           POKELDN_FIRMWARE_VERSION="${POKELDN_FIRMWARE_VERSION}")

# A diagnostic build: POKELDN_USB_BEACON=1 in the environment of idf.py (usbwatch.c).
if(DEFINED ENV{POKELDN_USB_BEACON})
    target_compile_definitions(${COMPONENT_LIB} PRIVATE POKELDN_USB_BEACON=1)
endif()

# The Bluetooth LE host link (ble.c): POKELDN_BLE=1 in the environment of idf.py, with
# sdkconfig.defaults.ble. docs/hardware_esp32.md, Bluetooth.
if(DEFINED ENV{POKELDN_BLE})
    target_compile_definitions(${COMPONENT_LIB} PRIVATE POKELDN_BLE=1)
endif()
