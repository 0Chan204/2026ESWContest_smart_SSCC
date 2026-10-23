idf_component_register(
    SRCS "main.c" "induction_model.c" "induction_hw.c" "induction_network.c"
    INCLUDE_DIRS "."
    REQUIRES esp_driver_gpio esp_driver_i2c esp_driver_ledc esp_driver_rmt
             esp_wifi esp_netif esp_event esp_timer nvs_flash mqtt json heap
)
