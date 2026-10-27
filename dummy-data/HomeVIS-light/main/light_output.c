#include "light_output.h"

#include "driver/gpio.h"
#include "esp_check.h"
#include "sdkconfig.h"

#ifdef CONFIG_LIGHT_LED_WS2812
#include "driver/rmt_encoder.h"
#include "driver/rmt_tx.h"

static rmt_channel_handle_t s_channel;
static rmt_encoder_handle_t s_encoder;
/* One WS2812 pixel: 24 GRB data bits followed by a low reset/latch interval. */
static rmt_symbol_word_t s_symbols[25];
#endif

static const char *TAG = "light_output";
static bool s_initialized;
static bool s_written;
static bool s_power;

esp_err_t light_output_set(bool power)
{
    if (!s_initialized) {
        return ESP_ERR_INVALID_STATE;
    }
    if (s_written && s_power == power) {
        return ESP_OK;
    }
#ifdef CONFIG_LIGHT_LED_WS2812
    const uint8_t brightness = power ? CONFIG_LIGHT_LED_BRIGHTNESS : 0;
    /* White has identical G/R/B bytes. RMT at 10 MHz gives 100 ns per tick. */
    for (int bit = 0; bit < 24; ++bit) {
        const bool one = (brightness & (0x80 >> (bit % 8))) != 0;
        s_symbols[bit] = (rmt_symbol_word_t) {
            .level0 = 1,
            .duration0 = one ? 9 : 3,
            .level1 = 0,
            .duration1 = one ? 3 : 9,
        };
    }
    s_symbols[24] = (rmt_symbol_word_t) {
        .level0 = 0, .duration0 = 1500,
        .level1 = 0, .duration1 = 1500,
    }; /* 300 us reset also accommodates newer WS2812 revisions. */
    const rmt_transmit_config_t transmit = {.loop_count = 0};
    ESP_RETURN_ON_ERROR(rmt_transmit(s_channel, s_encoder, s_symbols,
                                   sizeof(s_symbols), &transmit), TAG, "LED transmit failed");
    /* Complete the physical write before the command is acknowledged. */
    ESP_RETURN_ON_ERROR(rmt_tx_wait_all_done(s_channel, 100), TAG, "LED transmit timed out");
#else
    int level = power ? 1 : 0;
#ifdef CONFIG_LIGHT_LED_ACTIVE_LOW
    level = !level;
#endif
    ESP_RETURN_ON_ERROR(gpio_set_level(CONFIG_LIGHT_LED_GPIO, level), TAG, "LED GPIO write failed");
#endif
    s_written = true;
    s_power = power;
    return ESP_OK;
}

esp_err_t light_output_init(void)
{
    if (s_initialized) {
        return ESP_ERR_INVALID_STATE;
    }
    if (!GPIO_IS_VALID_OUTPUT_GPIO(CONFIG_LIGHT_LED_GPIO)) {
        ESP_LOGE(TAG, "GPIO%d is not an output GPIO on this chip", CONFIG_LIGHT_LED_GPIO);
        return ESP_ERR_INVALID_ARG;
    }
#ifdef CONFIG_LIGHT_LED_WS2812
    const rmt_tx_channel_config_t channel = {
        .gpio_num = CONFIG_LIGHT_LED_GPIO,
        .clk_src = RMT_CLK_SRC_DEFAULT,
        .resolution_hz = 10000000,
        .mem_block_symbols = 64,
        .trans_queue_depth = 1,
    };
    ESP_RETURN_ON_ERROR(rmt_new_tx_channel(&channel, &s_channel), TAG, "Cannot create LED RMT channel");
    const rmt_copy_encoder_config_t encoder = {};
    esp_err_t error = rmt_new_copy_encoder(&encoder, &s_encoder);
    if (error != ESP_OK) {
        rmt_del_channel(s_channel);
        return error;
    }
    error = rmt_enable(s_channel);
    if (error != ESP_OK) {
        rmt_del_encoder(s_encoder);
        rmt_del_channel(s_channel);
        return error;
    }
    ESP_LOGI(TAG, "On-board WS2812 LED: GPIO%d, white brightness=%d",
             CONFIG_LIGHT_LED_GPIO, CONFIG_LIGHT_LED_BRIGHTNESS);
#else
    const gpio_config_t config = {
        .pin_bit_mask = UINT64_C(1) << CONFIG_LIGHT_LED_GPIO,
        .mode = GPIO_MODE_OUTPUT,
    };
    ESP_RETURN_ON_ERROR(gpio_config(&config), TAG, "Cannot configure LED GPIO");
    ESP_LOGI(TAG, "On-board GPIO LED: GPIO%d", CONFIG_LIGHT_LED_GPIO);
#endif
    s_initialized = true;
    return light_output_set(false);
}
