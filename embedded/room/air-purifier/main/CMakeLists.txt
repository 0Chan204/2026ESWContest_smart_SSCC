idf_component_register(
    SRCS "main.c" "air_model.c" "air_hardware.c" "air_network.c"
    INCLUDE_DIRS "."
    REQUIRES esp_driver_gpio esp_adc esp_wifi esp_netif esp_event
             esp_timer nvs_flash mqtt json mbedtls
)
