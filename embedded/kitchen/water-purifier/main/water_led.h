#pragma once
#include "water_model.h"
#include <stdint.h>

#define WP_LED_COUNT 8
#define WP_LED_CLOCK_HZ 3200000
#define WP_LED_RESET_BYTES 128
#define WP_LED_FRAME_BYTES (2 * WP_LED_RESET_BYTES + WP_LED_COUNT * 3 * 4)
void wp_led_encode(bool dispensing, wp_water_type_t water_type, uint8_t brightness, uint8_t frame[WP_LED_FRAME_BYTES]);
