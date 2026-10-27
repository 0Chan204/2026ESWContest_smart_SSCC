idf_component_register(
    SRCS "main.c" "induction_payload.c"
    INCLUDE_DIRS "."
    PRIV_REQUIRES console esp_event esp_netif esp_wifi esp_timer esp_hw_support
                  nvs_flash mqtt json
)
