#pragma once
#include "water_model.h"

#define WP_SCREEN_BYTES (128 * 64 / 8)
/* SSD1306 page layout; idle selection or elapsed dispensing volume. */
void wp_screen_render(const wp_state_t *state, int64_t now, uint8_t frame[WP_SCREEN_BYTES]);
