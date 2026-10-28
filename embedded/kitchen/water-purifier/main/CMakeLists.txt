idf_component_register(
    SRCS "main.c" "water_model.c" "water_hardware.c" "water_led.c" "water_display.c" "water_screen.c" "water_network.c"
    INCLUDE_DIRS "."
    REQUIRES esp_driver_spi esp_driver_gpio esp_driver_i2c esp_wifi esp_netif esp_event
             esp_timer nvs_flash mqtt json mbedtls
)
