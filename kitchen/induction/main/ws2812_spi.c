#include "ws2812_spi.h"
#include <string.h>

void ws2812_spi_encode(const uint8_t pixels[INDUCTION_LEDS * 3],
                       uint8_t frame[WS2812_SPI_FRAME_BYTES])
{
    /* At 3.2MHz: 0 -> 1000 (312.5ns high), 1 -> 1110 (937.5ns high).
       Four SPI bits form one 1.25us WS2812 bit; each reset is 320us low. */
    memset(frame,0,WS2812_SPI_FRAME_BYTES);
    unsigned out=WS2812_SPI_RESET_BYTES;
    for (unsigned i=0;i<INDUCTION_LEDS*3;i++) {
        for (int shift=6;shift>=0;shift-=2) {
            uint8_t pair=(pixels[i] >> shift) & 3;
            uint8_t first=(pair & 2) ? 0xe : 0x8;
            uint8_t second=(pair & 1) ? 0xe : 0x8;
            frame[out++]=(uint8_t)((first << 4) | second);
        }
    }
}
