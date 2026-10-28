#include "water_hardware.h"
#include "sdkconfig.h"
#include "water_screen.h"
#include <string.h>
#include "driver/i2c_master.h"
#include "esp_check.h"
static const char *TAG = "water_display";
static i2c_master_bus_handle_t s_bus;
static i2c_master_dev_handle_t s_oled;
static uint8_t s_framebuffer[128 * 8];
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

static esp_err_t oled_init(void)
{
    const uint8_t commands[] = {
        0x00,0xAE,0x20,0x00,0xB0,0xC8,0x00,0x10,0x40,0x81,0x7F,
        0xA1,0xA6,0xA8,0x3F,0xA4,0xD3,0x00,0xD5,0x80,0xD9,0xF1,
        0xDA,0x12,0xDB,0x40,0x8D,0x14,0xAF
    };
    return oled_write(commands, sizeof(commands));
}

esp_err_t wp_display_init(void)
{
    i2c_master_bus_config_t bus = {.i2c_port = 0, .sda_io_num = CONFIG_WP_SDA_GPIO,
        .scl_io_num = CONFIG_WP_SCL_GPIO, .clk_source = I2C_CLK_SRC_DEFAULT,
        .glitch_ignore_cnt = 7, .flags.enable_internal_pullup = true};
    ESP_RETURN_ON_ERROR(i2c_new_master_bus(&bus, &s_bus), TAG, "OLED bus");
    i2c_device_config_t oled = {.dev_addr_length = I2C_ADDR_BIT_LEN_7,
        .device_address = CONFIG_WP_OLED_ADDRESS, .scl_speed_hz = 100000};
    ESP_RETURN_ON_ERROR(i2c_master_bus_add_device(s_bus, &oled, &s_oled), TAG, "OLED device");
    return oled_init();
}

esp_err_t wp_display_update(const wp_state_t *state, int64_t now)
{
    if (!s_oled) return ESP_ERR_INVALID_STATE;
    static bool was_dispensing;
    static int64_t displayed_start;
    bool first_frame = state->dispensing &&
        (!was_dispensing || state->started_us != displayed_start);
    /* Always show zero on the first successfully sent frame of a new run. */
    wp_screen_render(state, first_frame ? state->started_us : now, s_framebuffer);
    esp_err_t error = oled_flush();
    if (error == ESP_OK) {
        was_dispensing = state->dispensing;
        displayed_start = state->started_us;
    }
    return error;
}
