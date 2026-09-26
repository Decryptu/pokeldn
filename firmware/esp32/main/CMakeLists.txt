idf_component_register(
    SRCS "radio.c" "wire.c" "led.c"
    INCLUDE_DIRS "."
    PRIV_REQUIRES esp_wifi wpa_supplicant esp_driver_uart esp_driver_ledc esp_driver_gpio esp_timer nvs_flash esp_event)
