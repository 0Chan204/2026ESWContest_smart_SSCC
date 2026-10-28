idf_component_register(
    SRCS "main.c" "light_model.c" "light_output.c" "light_network.c"
    INCLUDE_DIRS "."
    REQUIRES esp_driver_gpio esp_driver_rmt esp_wifi esp_netif esp_event
             esp_timer nvs_flash mqtt json mbedtls
)
