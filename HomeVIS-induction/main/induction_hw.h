#pragma once
#include "induction_model.h"
#include "esp_err.h"
void induction_input_init(void);
void induction_led_init(void);
esp_err_t induction_led_write(const uint8_t pixels[INDUCTION_LEDS * 3]);
void induction_io_init(void);
void induction_io_update(const induction_state_t *state, bool online);
esp_err_t induction_read_temperature(float *temperature);
void induction_sound_init(void);
void induction_sound(bool on, bool alarm);
