idf_build_get_property(idf_target IDF_TARGET)
if(idf_target STREQUAL "esp32s3" OR idf_target STREQUAL "esp32c3" OR idf_target STREQUAL "esp32c6")
    set(wire_driver esp_driver_usb_serial_jtag)
elseif(idf_target STREQUAL "esp32")
    set(wire_driver esp_driver_uart)
else()
    message(FATAL_ERROR "pokeldn supports esp32, esp32s3, esp32c3 and esp32c6 targets only")
endif()

set(POKELDN_DISPLAY "OLED" CACHE STRING "Display profile: OLED or E32R40T")
set_property(CACHE POKELDN_DISPLAY PROPERTY STRINGS OLED E32R40T)
if(POKELDN_DISPLAY STREQUAL "E32R40T")
    if(NOT idf_target STREQUAL "esp32")
        message(FATAL_ERROR "E32R40T GPIO profile is supported on the original ESP32 target only")
    endif()
    set(display_profile_source "display_e32r40t.c")
    set(display_driver esp_driver_spi)
    set(display_profile_definition POKELDN_DISPLAY_TFT=1)
elseif(POKELDN_DISPLAY STREQUAL "OLED")
    set(display_profile_source "display_oled.c")
    set(display_driver esp_driver_i2c)
else()
    message(FATAL_ERROR "Unsupported POKELDN_DISPLAY='${POKELDN_DISPLAY}'; choose OLED or E32R40T")
endif()

if(DEFINED ENV{POKELDN_BLE})
    set(ble_component bt)
endif()

idf_component_register(
    SRCS "radio.c" "ble.c" "wire.c" "led.c" "usbwatch.c" "display.c" ${display_profile_source} "scene.c" "screen.c"
    INCLUDE_DIRS "."
    PRIV_REQUIRES esp_app_format esp_wifi wpa_supplicant ${wire_driver} esp_driver_ledc esp_driver_gpio ${display_driver} esp_timer nvs_flash esp_event esp_driver_spi ${ble_component})

if(display_profile_definition)
    target_compile_definitions(${COMPONENT_LIB} PRIVATE ${display_profile_definition})
endif()

target_compile_definitions(${COMPONENT_LIB} PRIVATE POKELDN_FIRMWARE_VERSION="${POKELDN_FIRMWARE_VERSION}")

# A diagnostic build: POKELDN_USB_BEACON=1 in the environment of idf.py (usbwatch.c).
if(DEFINED ENV{POKELDN_USB_BEACON})
    target_compile_definitions(${COMPONENT_LIB} PRIVATE POKELDN_USB_BEACON=1)
endif()

# The Bluetooth LE host link (ble.c): POKELDN_BLE=1 in the environment of idf.py, with
# sdkconfig.defaults.ble. docs/hardware_esp32.md, Bluetooth.
if(DEFINED ENV{POKELDN_BLE})
    target_compile_definitions(${COMPONENT_LIB} PRIVATE POKELDN_BLE=1)
endif()
