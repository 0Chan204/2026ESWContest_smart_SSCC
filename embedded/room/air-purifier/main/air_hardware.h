#pragma once
#include <stdbool.h>
#include "esp_err.h"

esp_err_t ap_hardware_init(void);
esp_err_t ap_output_fan(bool power);
esp_err_t ap_read_sensor(int *raw, int *adc_mv);
