#pragma once

#include <stdbool.h>
#include "esp_err.h"

/* Initialize once before the state task. All later writes belong to that task. */
esp_err_t light_output_init(void);
esp_err_t light_output_set(bool power);
