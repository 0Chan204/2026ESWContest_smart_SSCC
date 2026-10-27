idf_component_register(
    SRCS "main.c" "light_model.c" "light_output.c"
    INCLUDE_DIRS "."
    PRIV_REQUIRES console esp_event esp_netif esp_wifi esp_timer esp_hw_support
                  nvs_flash mqtt json esp_driver_gpio esp_driver_rmt
)
