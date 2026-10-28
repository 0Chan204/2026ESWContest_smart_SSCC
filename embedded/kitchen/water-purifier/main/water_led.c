#include "water_led.h"
#include <string.h>

void wp_led_encode(bool dispensing, wp_water_type_t water_type, uint8_t brightness, uint8_t frame[WP_LED_FRAME_BYTES])
{
    /* WS2812B GRB order: hot water is red; cold/purified water is blue.
     * 3.2 MHz SPI: 1000/1110 represent 0/1, with 320 us LOW at both ends. */
    memset(frame, 0, WP_LED_FRAME_BYTES);
    unsigned out = WP_LED_RESET_BYTES;
    unsigned color_channel = water_type == WP_HOT ? 1 : 2;
    for (unsigned channel = 0; channel < WP_LED_COUNT * 3; ++channel) {
        uint8_t value = dispensing && channel % 3 == color_channel ? brightness : 0;
        for (int shift = 6; shift >= 0; shift -= 2) {
            uint8_t pair = (value >> shift) & 3;
            frame[out++] = (uint8_t)(((pair & 2 ? 0xe : 0x8) << 4) | (pair & 1 ? 0xe : 0x8));
        }
    }
}
