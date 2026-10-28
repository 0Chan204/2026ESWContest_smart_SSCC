#pragma once

#include <stdbool.h>
#include "esp_err.h"

esp_err_t rl_output_init(void);
esp_err_t rl_output_light(int brightness_percent);
