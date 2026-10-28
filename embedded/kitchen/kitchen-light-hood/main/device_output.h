#pragma once

#include <stdbool.h>
#include "esp_err.h"

esp_err_t klh_output_init(void);
esp_err_t klh_output_light(int brightness_percent);
esp_err_t klh_output_fan(bool power);
