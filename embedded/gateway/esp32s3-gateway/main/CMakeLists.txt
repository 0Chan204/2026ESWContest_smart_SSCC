idf_component_register(SRCS "main.c" "gateway_wire.c" INCLUDE_DIRS "."
    REQUIRES esp_wifi esp_netif esp_event esp_timer nvs_flash
             esp_driver_usb_serial_jtag esp_driver_uart lwip)
