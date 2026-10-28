#include "water_hardware.h"
#include "sdkconfig.h"
#include "driver/gpio.h"
#include "esp_check.h"
#include "driver/spi_master.h"
#include "esp_attr.h"
#include "water_led.h"

static const char *TAG = "water_hardware";
static const int s_touch_pins[] = {CONFIG_WP_TOUCH_1_GPIO, CONFIG_WP_TOUCH_2_GPIO,
    CONFIG_WP_TOUCH_3_GPIO, CONFIG_WP_TOUCH_4_GPIO};
static bool s_ready;
static spi_device_handle_t s_led;
static DMA_ATTR uint8_t s_frame[WP_LED_FRAME_BYTES];

esp_err_t wp_output(bool dispensing, wp_water_type_t water_type)
{
    if (!s_ready) return ESP_ERR_INVALID_STATE;
    wp_led_encode(dispensing, water_type, CONFIG_WP_LED_BRIGHTNESS, s_frame);
    spi_transaction_t transaction = {.length = sizeof(s_frame) * 8, .tx_buffer = s_frame};
    return spi_device_transmit(s_led, &transaction);
}

bool wp_touch_active(unsigned index)
{
    if (index >= 4) return false;
#ifdef CONFIG_WP_TOUCH_ACTIVE_LOW
    return gpio_get_level(s_touch_pins[index]) == 0;
#else
    return gpio_get_level(s_touch_pins[index]) != 0;
#endif
}

esp_err_t wp_hardware_init(void)
{
    const int pins[] = {CONFIG_WP_LED_GPIO,
        CONFIG_WP_SDA_GPIO, CONFIG_WP_SCL_GPIO, CONFIG_WP_TOUCH_1_GPIO,
        CONFIG_WP_TOUCH_2_GPIO, CONFIG_WP_TOUCH_3_GPIO, CONFIG_WP_TOUCH_4_GPIO};
    for (unsigned i = 0; i < sizeof(pins)/sizeof(pins[0]); ++i) {
        int pin = pins[i];
        bool allowed = (pin >= 0 && pin <= 3) || pin == 6 || pin == 7 || (pin >= 18 && pin <= 23);
        ESP_RETURN_ON_FALSE(allowed, ESP_ERR_INVALID_ARG, TAG, "Unsupported GPIO%d", pin);
        for (unsigned j = 0; j < i; ++j)
            ESP_RETURN_ON_FALSE(pin != pins[j], ESP_ERR_INVALID_ARG, TAG, "Duplicate GPIO%d", pin);
    }
    spi_bus_config_t bus = {
        .mosi_io_num = CONFIG_WP_LED_GPIO, .miso_io_num = -1, .sclk_io_num = -1,
        .quadwp_io_num = -1, .quadhd_io_num = -1, .max_transfer_sz = sizeof(s_frame),
    };
    ESP_RETURN_ON_ERROR(spi_bus_initialize(SPI2_HOST, &bus, SPI_DMA_CH_AUTO), TAG, "LED SPI bus");
    spi_device_interface_config_t device = {
        .clock_speed_hz = WP_LED_CLOCK_HZ, .mode = 0, .spics_io_num = -1,
        .queue_size = 1, .flags = SPI_DEVICE_HALFDUPLEX,
    };
    ESP_RETURN_ON_ERROR(spi_bus_add_device(SPI2_HOST, &device, &s_led), TAG, "LED SPI device");
    s_ready = true;
    ESP_RETURN_ON_ERROR(wp_output(false, WP_PURIFIED), TAG, "Initial LED OFF");
    gpio_config_t touch = {.mode = GPIO_MODE_INPUT};
    for (unsigned i = 0; i < 4; ++i) touch.pin_bit_mask |= 1ULL << s_touch_pins[i];
#ifdef CONFIG_WP_TOUCH_ACTIVE_LOW
    touch.pull_up_en = GPIO_PULLUP_ENABLE;
#else
    touch.pull_down_en = GPIO_PULLDOWN_ENABLE;
#endif
    ESP_RETURN_ON_ERROR(gpio_config(&touch), TAG, "Touch GPIO");
    ESP_LOGI(TAG, "WS2812B GPIO%d: %d red/blue LEDs, brightness=%d; touch=%d/%d/%d/%d",
        CONFIG_WP_LED_GPIO, WP_LED_COUNT, CONFIG_WP_LED_BRIGHTNESS,
        s_touch_pins[0], s_touch_pins[1], s_touch_pins[2], s_touch_pins[3]);
    return ESP_OK;
}
