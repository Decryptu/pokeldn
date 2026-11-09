idf_component_register(
    SRCS "bridge.c" "net.c" "web.c" "captive.c" "pixels.c" "battery.c"
    INCLUDE_DIRS "."
    EMBED_TXTFILES "index.html"
    PRIV_REQUIRES esp_app_format esp_driver_uart esp_driver_gpio esp_driver_rmt esp_adc esp_event esp_http_server esp_netif
                  esp_timer esp_wifi lwip nvs_flash)
