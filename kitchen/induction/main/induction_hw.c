#include "sdkconfig.h"
#include "induction_hw.h"
#include <stdio.h>
#include <string.h>
#include "driver/gpio.h"
#include "driver/i2c_master.h"
#include "driver/ledc.h"
#include "driver/spi_master.h"
#include "ws2812_spi.h"
#include "esp_attr.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

#define OLED_I2C_ADDRESS 0x3c
#define GY906_I2C_ADDRESS 0x5a
static const char *TAG __attribute__((unused)) = "induction_hw";
static i2c_master_bus_handle_t s_bus __attribute__((unused));
static i2c_master_dev_handle_t s_oled, s_gy906;
static bool s_oled_ready;
static uint8_t s_framebuffer[128 * 8];
static spi_device_handle_t s_rgb;
/* The full waveform is DMA-backed; no ISR needs to refill LED symbols. */
static DMA_ATTR uint8_t s_spi_frame[WS2812_SPI_FRAME_BYTES];
void induction_input_init(void)
{
    gpio_config_t touch = {.pin_bit_mask=1ULL << CONFIG_INDUCTION_TOUCH_GPIO,
        .mode=GPIO_MODE_INPUT, .pull_down_en=GPIO_PULLDOWN_ENABLE};
    ESP_ERROR_CHECK(gpio_config(&touch));
    gpio_config_t enc = {.pin_bit_mask=(1ULL << CONFIG_INDUCTION_ENCODER_A_GPIO) |
        (1ULL << CONFIG_INDUCTION_ENCODER_B_GPIO) | (1ULL << CONFIG_INDUCTION_ENCODER_SW_GPIO),
        .mode=GPIO_MODE_INPUT, .pull_up_en=GPIO_PULLUP_ENABLE};
    ESP_ERROR_CHECK(gpio_config(&enc));
}
void induction_led_init(void)
{
    spi_bus_config_t bus = {.mosi_io_num=CONFIG_INDUCTION_LED_GPIO,
        .miso_io_num=-1, .sclk_io_num=-1, .quadwp_io_num=-1, .quadhd_io_num=-1,
        .max_transfer_sz=sizeof(s_spi_frame)};
    ESP_ERROR_CHECK(spi_bus_initialize(SPI2_HOST,&bus,SPI_DMA_CH_AUTO));
    spi_device_interface_config_t device = {.clock_speed_hz=WS2812_SPI_CLOCK_HZ,
        .mode=0, .spics_io_num=-1, .queue_size=1, .flags=SPI_DEVICE_HALFDUPLEX};
    ESP_ERROR_CHECK(spi_bus_add_device(SPI2_HOST,&device,&s_rgb));
    const uint8_t off[INDUCTION_LEDS*3]={0};
    ESP_ERROR_CHECK(induction_led_write(off));
}
esp_err_t induction_led_write(const uint8_t pixels[INDUCTION_LEDS * 3])
{
    ws2812_spi_encode(pixels,s_spi_frame);
    spi_transaction_t transaction={.length=sizeof(s_spi_frame)*8,.tx_buffer=s_spi_frame};
    /* Returns only after DMA completion; the sole LED task then reuses this buffer. */
    return spi_device_transmit(s_rgb,&transaction);
}
/* 5x7 glyphs: space, A, E, F, N, O, P, R, W, C, T, -, 0..9 */
static const uint8_t s_font[][6] = {
    {0x00,0x00,0x00,0x00,0x00,0x00},
    {0x7E,0x11,0x11,0x11,0x7E,0x00},
    {0x7F,0x49,0x49,0x49,0x41,0x00},
    {0x7F,0x09,0x09,0x09,0x01,0x00},
    {0x7F,0x04,0x08,0x10,0x7F,0x00},
    {0x3E,0x41,0x41,0x41,0x3E,0x00},
    {0x7F,0x09,0x09,0x09,0x06,0x00},
    {0x7F,0x09,0x19,0x29,0x46,0x00},
    {0x3F,0x40,0x38,0x40,0x3F,0x00},
    {0x3E,0x41,0x41,0x41,0x22,0x00},
    {0x01,0x01,0x7F,0x01,0x01,0x00},
    {0x00,0x08,0x08,0x08,0x00,0x00},
    {0x3E,0x51,0x49,0x45,0x3E,0x00},
    {0x00,0x42,0x7F,0x40,0x00,0x00},
    {0x42,0x61,0x51,0x49,0x46,0x00},
    {0x21,0x41,0x45,0x4B,0x31,0x00},
    {0x18,0x14,0x12,0x7F,0x10,0x00},
    {0x27,0x45,0x45,0x45,0x39,0x00},
    {0x3C,0x4A,0x49,0x49,0x30,0x00},
    {0x01,0x71,0x09,0x05,0x03,0x00},
    {0x36,0x49,0x49,0x49,0x36,0x00},
    {0x06,0x49,0x49,0x29,0x1E,0x00},
    {0x7f,0x41,0x41,0x22,0x1c,0}, /* D */
    {0x7f,0x02,0x0c,0x02,0x7f,0}, /* M */
    {0x00,0x41,0x7f,0x41,0x00,0}, /* I */
    {0x7f,0x40,0x40,0x40,0x40,0}, /* L */
    {0x3e,0x41,0x49,0x49,0x7a,0}, /* G */
    {0x7f,0x08,0x08,0x08,0x7f,0}, /* H */
    {0x1f,0x20,0x40,0x20,0x1f,0}, /* V */
};

static uint8_t glyph_index(char c)
{
    const char *letters = " AEFNOPRW";
    const char *found = strchr(letters, c);
    if (found) return (uint8_t)(found - letters);
    if (c == 'C') return 9;
    if (c == 'T') return 10;
    if (c == '-') return 11;
    static const char extra_letters[] = "DMILGHV";
    const char *extra = strchr(extra_letters, c);
    if (extra) return 22 + (uint8_t)(extra - extra_letters);
    if (c >= '0' && c <= '9') return 12 + (uint8_t)(c - '0');
    return 0;
}

static esp_err_t oled_write(const uint8_t *data, size_t length)
{
    return i2c_master_transmit(s_oled, data, length, 100);
}

static esp_err_t oled_flush(void)
{
    const uint8_t window[] = {0x00, 0x21, 0, 127, 0x22, 0, 7};
    esp_err_t err = oled_write(window, sizeof(window));
    if (err != ESP_OK) return err;
    for (int offset = 0; offset < sizeof(s_framebuffer); offset += 16) {
        uint8_t packet[17] = {0x40};
        memcpy(packet + 1, s_framebuffer + offset, 16);
        err = oled_write(packet, sizeof(packet));
        if (err != ESP_OK) return err;
    }
    return ESP_OK;
}

static void oled_draw_text_2x(int x, int page, const char *text)
{
    while (*text && x < 116 && page < 7) {
        const uint8_t *glyph = s_font[glyph_index(*text++)];
        for (int column = 0; column < 6; column++) {
            uint8_t source = glyph[column], upper = 0, lower = 0;
            for (int bit = 0; bit < 4; bit++) {
                if (source & (1U << bit)) upper |= (uint8_t)(3U << (bit * 2));
            }
            for (int bit = 4; bit < 8; bit++) {
                if (source & (1U << bit)) lower |= (uint8_t)(3U << ((bit - 4) * 2));
            }
            s_framebuffer[page * 128 + x] = upper;
            s_framebuffer[page * 128 + x + 1] = upper;
            s_framebuffer[(page + 1) * 128 + x] = lower;
            s_framebuffer[(page + 1) * 128 + x + 1] = lower;
            x += 2;
        }
    }
}

static void oled_draw_text(int x, int page, const char *text)
{
    while (*text && x < 122 && page < 8) {
        const uint8_t *glyph = s_font[glyph_index(*text++)];
        for (int column = 0; column < 6; column++) {
            s_framebuffer[page * 128 + x++] = glyph[column];
        }
    }
}

static esp_err_t oled_init(void)
{
    const uint8_t commands[] = {
        0x00,0xAE,0x20,0x00,0xB0,0xC8,0x00,0x10,0x40,0x81,0x7F,
        0xA1,0xA6,0xA8,0x3F,0xA4,0xD3,0x00,0xD5,0x80,0xD9,0xF1,
        0xDA,0x12,0xDB,0x40,0x8D,0x14,0xAF
    };
    return oled_write(commands, sizeof(commands));
}

static esp_err_t gy906_read_object_temperature(float *temperature_c)
{
    const uint8_t object_temperature_register = 0x07;
    uint8_t response[3];
    esp_err_t err = i2c_master_transmit_receive(s_gy906,
                                                &object_temperature_register, 1,
                                                response, sizeof(response), 100);
    if (err != ESP_OK) return err;

    uint8_t pec_data[] = {
        GY906_I2C_ADDRESS << 1,
        object_temperature_register,
        (GY906_I2C_ADDRESS << 1) | 1,
        response[0], response[1]
    };
    uint8_t crc = 0;
    for (size_t i = 0; i < sizeof(pec_data); i++) {
        crc ^= pec_data[i];
        for (int bit = 0; bit < 8; bit++) {
            crc = (crc & 0x80) ? (uint8_t)((crc << 1) ^ 0x07) : (uint8_t)(crc << 1);
        }
    }
    if (crc != response[2]) return ESP_ERR_INVALID_CRC;

    uint16_t raw = (uint16_t)response[0] | ((uint16_t)response[1] << 8);
    if ((raw & 0x8000) || raw == 0) return ESP_ERR_INVALID_RESPONSE;
    *temperature_c = raw * 0.02f - 273.15f;
    return ESP_OK;
}


void induction_io_init(void)
{
    i2c_master_bus_config_t bus = {.i2c_port=0, .sda_io_num=CONFIG_INDUCTION_SDA_GPIO,
        .scl_io_num=CONFIG_INDUCTION_SCL_GPIO, .clk_source=I2C_CLK_SRC_DEFAULT,
        .glitch_ignore_cnt=7, .flags.enable_internal_pullup=true};
    ESP_ERROR_CHECK(i2c_new_master_bus(&bus, &s_bus));
#ifdef CONFIG_INDUCTION_OLED_ENABLE
    i2c_device_config_t oled = {.dev_addr_length=I2C_ADDR_BIT_LEN_7,
        .device_address=OLED_I2C_ADDRESS, .scl_speed_hz=400000};
    ESP_ERROR_CHECK(i2c_master_bus_add_device(s_bus, &oled, &s_oled));
    s_oled_ready = oled_init() == ESP_OK;
    if (!s_oled_ready) ESP_LOGW(TAG, "OLED unavailable; local controls remain active");
#endif
    i2c_device_config_t sensor = {.dev_addr_length=I2C_ADDR_BIT_LEN_7,
        .device_address=GY906_I2C_ADDRESS, .scl_speed_hz=100000};
    ESP_ERROR_CHECK(i2c_master_bus_add_device(s_bus, &sensor, &s_gy906));
}
void induction_io_update(const induction_state_t *state, bool online)
{
    if (!s_oled) return;
    if (!s_oled_ready) {
        s_oled_ready = oled_init() == ESP_OK;
        if (!s_oled_ready) return;
    }
    memset(s_framebuffer, 0, sizeof(s_framebuffer));
    oled_draw_text_2x(34, 0, "POWER");
    oled_draw_text_2x(46, 2, state->mode == ST_ON ? "ON" : "OFF");
    char line[24];
    snprintf(line, sizeof(line), "P %u", state->level);
    oled_draw_text(0, 5, line);
    if (state->temperature_valid) snprintf(line, sizeof(line), "T %.0f C", state->temperature);
    else strcpy(line, "T --- C");
    oled_draw_text(0, 7, line);
    const char *mode=state->mode==ST_COOLING ? "COOLING" :
        state->mode==ST_OVERHEATED ? "OVERHEAT" : state->mode==ST_ON ? "ON" : "OFF";
    oled_draw_text(0, 6, mode);
    /* N = subscribed to MQTT commands, dash = offline. */
    oled_draw_text(108, 5, online ? "N" : "-");
    if (state->alarm) oled_draw_text(96, 5, "A");
    if (oled_flush() != ESP_OK) s_oled_ready = false;
}
esp_err_t induction_read_temperature(float *temperature)
{
    return s_gy906 ? gy906_read_object_temperature(temperature) : ESP_ERR_INVALID_STATE;
}
void induction_sound_init(void)
{
    ledc_timer_config_t timer = {.speed_mode=LEDC_LOW_SPEED_MODE,
        .duty_resolution=LEDC_TIMER_10_BIT, .timer_num=LEDC_TIMER_0,
        .freq_hz=2000, .clk_cfg=LEDC_AUTO_CLK};
    ESP_ERROR_CHECK(ledc_timer_config(&timer));
    ledc_channel_config_t channel = {.gpio_num=CONFIG_INDUCTION_BUZZER_GPIO,
        .speed_mode=LEDC_LOW_SPEED_MODE, .channel=LEDC_CHANNEL_0,
        .timer_sel=LEDC_TIMER_0, .duty=0};
    ESP_ERROR_CHECK(ledc_channel_config(&channel));
}
void induction_sound(bool on, bool alarm)
{
    unsigned notes[2] = {alarm ? 3000 : on ? 1800 : 2200, alarm ? 3000 : on ? 2600 : 1200};
    for (unsigned i=0; i<2; i++) {
        ledc_set_freq(LEDC_LOW_SPEED_MODE, LEDC_TIMER_0, notes[i]);
        ledc_set_duty(LEDC_LOW_SPEED_MODE, LEDC_CHANNEL_0, 128);
        ledc_update_duty(LEDC_LOW_SPEED_MODE, LEDC_CHANNEL_0);
        vTaskDelay(pdMS_TO_TICKS(70));
        ledc_set_duty(LEDC_LOW_SPEED_MODE, LEDC_CHANNEL_0, 0);
        ledc_update_duty(LEDC_LOW_SPEED_MODE, LEDC_CHANNEL_0);
        vTaskDelay(pdMS_TO_TICKS(25));
    }
}
