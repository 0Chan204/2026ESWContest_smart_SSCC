#pragma once
#include "induction_model.h"
#define WS2812_SPI_CLOCK_HZ 3200000
#define WS2812_SPI_RESET_BYTES 128
#define WS2812_SPI_DATA_BYTES (INDUCTION_LEDS * 3 * 4)
#define WS2812_SPI_FRAME_BYTES (WS2812_SPI_RESET_BYTES * 2 + WS2812_SPI_DATA_BYTES)
void ws2812_spi_encode(const uint8_t pixels[INDUCTION_LEDS * 3],
                       uint8_t frame[WS2812_SPI_FRAME_BYTES]);
