#include "water_screen.h"
#include "water_font.h"
#include <stdio.h>
#include <string.h>

/* Existing project 5x7 digits, followed by lowercase m and uppercase L. */
static const uint8_t s_digits[][5] = {
    {0x3e,0x51,0x49,0x45,0x3e}, {0x00,0x42,0x7f,0x40,0x00},
    {0x42,0x61,0x51,0x49,0x46}, {0x21,0x41,0x45,0x4b,0x31},
    {0x18,0x14,0x12,0x7f,0x10}, {0x27,0x45,0x45,0x45,0x39},
    {0x3c,0x4a,0x49,0x49,0x30}, {0x01,0x71,0x09,0x05,0x03},
    {0x36,0x49,0x49,0x49,0x36}, {0x06,0x49,0x49,0x29,0x1e},
    {0x7c,0x04,0x18,0x04,0x78}, {0x7f,0x40,0x40,0x40,0x40},
};

static void pixel(uint8_t *frame, int x, int y)
{
    if (x >= 0 && x < 128 && y >= 0 && y < 64)
        frame[(y / 8) * 128 + x] |= 1U << (y % 8);
}

static void korean(uint8_t *frame, unsigned glyph, int x, int y)
{
    for (int row = 0; row < 24; ++row)
        for (int col = 0; col < 24; ++col)
            if (s_korean[glyph][row] & (1U << (23 - col))) pixel(frame, x + col, y + row);
}

void wp_screen_render(const wp_state_t *state, int64_t now, uint8_t frame[WP_SCREEN_BYTES])
{
    memset(frame, 0, WP_SCREEN_BYTES);
    /* Center two Korean glyphs with a four-pixel gap: 온수 / 냉수 / 정수. */
    unsigned kind = state->water_type == WP_HOT ? 0 : state->water_type == WP_COLD ? 1 : 2;
    korean(frame, kind, 38, 8);
    korean(frame, 3, 66, 8);
    int volume = state->dispensing ? wp_estimated_ml(state, now) : state->selected_ml;
    char line[16];
    snprintf(line, sizeof(line), "%dmL", volume);
    int x = (128 - ((int)strlen(line) * 6 - 1) * 2) / 2;
    for (const char *p = line; *p; ++p, x += 12) {
        unsigned index = *p == 'm' ? 10 : *p == 'L' ? 11 : (unsigned)(*p - '0');
        if (index >= sizeof(s_digits) / sizeof(s_digits[0])) continue;
        for (int col = 0; col < 5; ++col)
            for (int row = 0; row < 7; ++row)
                if (s_digits[index][col] & (1U << row))
                    for (int dy = 0; dy < 2; ++dy)
                        for (int dx = 0; dx < 2; ++dx)
                            pixel(frame, x + col * 2 + dx, 40 + row * 2 + dy);
    }
}
