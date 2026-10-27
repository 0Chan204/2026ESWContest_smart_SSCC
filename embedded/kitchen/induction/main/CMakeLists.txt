idf_component_register(
    SRCS "main.c" "induction_model.c" "induction_hw.c" "induction_network.c" "ws2812_spi.c"
    INCLUDE_DIRS "."
    REQUIRES esp_driver_gpio esp_driver_i2c esp_driver_ledc esp_driver_spi
             esp_wifi esp_netif esp_event esp_timer nvs_flash mqtt json heap
)
