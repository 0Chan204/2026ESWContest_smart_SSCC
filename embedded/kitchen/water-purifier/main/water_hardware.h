#pragma once
#include "water_model.h"
#include "esp_err.h"
esp_err_t wp_hardware_init(void);
esp_err_t wp_output(bool dispensing, wp_water_type_t water_type);
bool wp_touch_active(unsigned index);
/* OLED is owned by its separate task so I2C never blocks dispensing control. */
esp_err_t wp_display_init(void);
esp_err_t wp_display_update(const wp_state_t *state, int64_t now);
