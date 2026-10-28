#include "device_output.h"

#include "sdkconfig.h"
#include "driver/gpio.h"
#include "driver/rmt_encoder.h"
#include "driver/rmt_tx.h"
#include "esp_check.h"

static const char *TAG = "kitchen_output";
static rmt_channel_handle_t s_channel;
static rmt_encoder_handle_t s_encoder;
static rmt_symbol_word_t s_symbols[24 * CONFIG_KLH_LED_COUNT + 1];
static bool s_ready;
static bool s_tx_pending;
static int s_brightness = -1;

static bool usable_gpio(int pin)
{
    /* Common C6 header GPIOs: exclude strapping, USB, UART0, flash, and
     * package-dependent GPIO10/11/14 so the defaults work across C6 modules. */
    bool common_header = (pin >= 0 && pin <= 3) || pin == 6 || pin == 7 ||
                         (pin >= 18 && pin <= 23);
    return common_header && GPIO_IS_VALID_OUTPUT_GPIO(pin);
}

static int relay_level(bool power)
{
#ifdef CONFIG_KLH_RELAY_ACTIVE_LOW
    return power ? 0 : 1;
#else
    return power ? 1 : 0;
#endif
}

esp_err_t klh_output_fan(bool power)
{
    if (!s_ready) return ESP_ERR_INVALID_STATE;
    return gpio_set_level(CONFIG_KLH_RELAY_GPIO, relay_level(power));
}

esp_err_t klh_output_light(int brightness_percent)
{
    if (!s_ready) return ESP_ERR_INVALID_STATE;
    if (brightness_percent < 0 || brightness_percent > 100) return ESP_ERR_INVALID_ARG;
    /* A timed-out RMT transfer may still reference s_symbols. Drain it before
     * rewriting that buffer for another command or animation step. */
    if (s_tx_pending) {
        ESP_RETURN_ON_ERROR(rmt_tx_wait_all_done(s_channel, 1000), TAG, "Previous LED transfer still pending");
        s_tx_pending = false;
    }
    if (brightness_percent == s_brightness) return ESP_OK;
    const uint8_t value = (brightness_percent * CONFIG_KLH_LED_MAX_BRIGHTNESS + 50) / 100;
    for (int i = 0; i < 24 * CONFIG_KLH_LED_COUNT; ++i) {
        /* White: each pixel has identical G/R/B values, MSB first, 800 kHz. */
        bool one = (value & (0x80 >> (i % 8))) != 0;
        s_symbols[i] = (rmt_symbol_word_t) {
            .level0 = 1, .duration0 = one ? 8 : 4,
            .level1 = 0, .duration1 = one ? 5 : 9,
        };
    }
    s_symbols[24 * CONFIG_KLH_LED_COUNT] = (rmt_symbol_word_t) {
        .level0 = 0, .duration0 = 1500, .level1 = 0, .duration1 = 1500,
    }; /* 300 us latch, including newer WS2812B revisions. */
    const rmt_transmit_config_t config = {.loop_count = 0};
    ESP_RETURN_ON_ERROR(rmt_transmit(s_channel, s_encoder, s_symbols, sizeof(s_symbols), &config),
                        TAG, "WS2812B transmit failed");
    s_tx_pending = true;
    s_brightness = -1;
    ESP_RETURN_ON_ERROR(rmt_tx_wait_all_done(s_channel, 1000), TAG, "WS2812B transmit timeout");
    s_tx_pending = false;
    s_brightness = brightness_percent;
    return ESP_OK;
}

esp_err_t klh_output_init(void)
{
    if (!usable_gpio(CONFIG_KLH_LED_GPIO) || !usable_gpio(CONFIG_KLH_RELAY_GPIO) ||
        CONFIG_KLH_LED_GPIO == CONFIG_KLH_RELAY_GPIO) {
        ESP_LOGE(TAG, "Choose distinct C6 header GPIOs from 0/1/2/3/6/7/18/19/20/21/22/23");
        return ESP_ERR_INVALID_ARG;
    }
    /* Preload the OFF level before enabling output, including active-low relays. */
    ESP_RETURN_ON_ERROR(gpio_reset_pin(CONFIG_KLH_RELAY_GPIO), TAG, "Relay reset failed");
    ESP_RETURN_ON_ERROR(gpio_set_level(CONFIG_KLH_RELAY_GPIO, relay_level(false)), TAG, "Relay latch failed");
    ESP_RETURN_ON_ERROR(gpio_set_direction(CONFIG_KLH_RELAY_GPIO, GPIO_MODE_OUTPUT), TAG, "Relay output failed");
    const rmt_tx_channel_config_t channel = {
        .gpio_num = CONFIG_KLH_LED_GPIO, .clk_src = RMT_CLK_SRC_DEFAULT,
        .resolution_hz = 10000000, .mem_block_symbols = 48,
        .trans_queue_depth = 1, .intr_priority = 3,
    };
    ESP_RETURN_ON_ERROR(rmt_new_tx_channel(&channel, &s_channel), TAG, "RMT channel failed");
    const rmt_copy_encoder_config_t encoder = {};
    esp_err_t err = rmt_new_copy_encoder(&encoder, &s_encoder);
    if (err != ESP_OK) {
        rmt_del_channel(s_channel);
        return err;
    }
    err = rmt_enable(s_channel);
    if (err != ESP_OK) {
        rmt_del_encoder(s_encoder);
        rmt_del_channel(s_channel);
        return err;
    }
    s_ready = true;
    ESP_RETURN_ON_ERROR(klh_output_light(0), TAG, "Initial LED OFF failed");
    ESP_LOGI(TAG, "WS2812B GPIO%d, pixels=%d, channel cap=%d; relay GPIO%d (%s)",
             CONFIG_KLH_LED_GPIO, CONFIG_KLH_LED_COUNT, CONFIG_KLH_LED_MAX_BRIGHTNESS,
             CONFIG_KLH_RELAY_GPIO, relay_level(true) ? "active high" : "active low");
    return ESP_OK;
}
