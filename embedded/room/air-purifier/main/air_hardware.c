#include "air_hardware.h"
#include "sdkconfig.h"
#include "driver/gpio.h"
#include "esp_adc/adc_oneshot.h"
#include "esp_adc/adc_cali.h"
#include "esp_adc/adc_cali_scheme.h"
#include "esp_check.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

static const char *TAG = "air_hardware";
static adc_oneshot_unit_handle_t s_adc;
static adc_cali_handle_t s_calibration;
static adc_channel_t s_channel;
static bool s_relay_ready;

static int relay_level(bool power)
{
#ifdef CONFIG_AP_RELAY_ACTIVE_LOW
    return power ? 0 : 1;
#else
    return power ? 1 : 0;
#endif
}

esp_err_t ap_output_fan(bool power)
{
    if (!s_relay_ready) return ESP_ERR_INVALID_STATE;
    return gpio_set_level(CONFIG_AP_RELAY_GPIO, relay_level(power));
}

esp_err_t ap_hardware_init(void)
{
    int relay = CONFIG_AP_RELAY_GPIO, sensor = CONFIG_AP_MQ135_GPIO;
    bool relay_allowed = (relay >= 0 && relay <= 3) || relay == 6 || relay == 7 ||
                         (relay >= 18 && relay <= 23);
    bool sensor_allowed = (sensor >= 0 && sensor <= 3) || sensor == 6;
    ESP_RETURN_ON_FALSE(relay_allowed && sensor_allowed && relay != sensor,
                        ESP_ERR_INVALID_ARG, TAG, "Invalid or overlapping GPIOs");
    ESP_RETURN_ON_FALSE(CONFIG_AP_GOOD_RAW < CONFIG_AP_BAD_RAW &&
                        CONFIG_AP_BAD_RAW < CONFIG_AP_VERY_BAD_RAW,
                        ESP_ERR_INVALID_ARG, TAG, "Thresholds must satisfy good < bad < very_bad");
    /* Set the output latch before enabling output to avoid an active-low pulse. */
    ESP_RETURN_ON_ERROR(gpio_set_level(relay, relay_level(false)), TAG, "Relay OFF latch");
    gpio_config_t config = {
        .pin_bit_mask = 1ULL << relay, .mode = GPIO_MODE_OUTPUT,
        .pull_up_en = relay_level(false) ? GPIO_PULLUP_ENABLE : GPIO_PULLUP_DISABLE,
        .pull_down_en = relay_level(false) ? GPIO_PULLDOWN_DISABLE : GPIO_PULLDOWN_ENABLE,
    };
    ESP_RETURN_ON_ERROR(gpio_config(&config), TAG, "Relay GPIO");
    s_relay_ready = true;
    adc_unit_t unit;
    ESP_RETURN_ON_ERROR(adc_oneshot_io_to_channel(sensor, &unit, &s_channel), TAG, "ADC GPIO");
    ESP_RETURN_ON_FALSE(unit == ADC_UNIT_1, ESP_ERR_INVALID_ARG, TAG, "ADC1 required");
    adc_oneshot_unit_init_cfg_t init = {.unit_id = unit};
    ESP_RETURN_ON_ERROR(adc_oneshot_new_unit(&init, &s_adc), TAG, "ADC unit");
    adc_oneshot_chan_cfg_t channel = {.atten = ADC_ATTEN_DB_12, .bitwidth = ADC_BITWIDTH_12};
    ESP_RETURN_ON_ERROR(adc_oneshot_config_channel(s_adc, s_channel, &channel), TAG, "ADC channel");
    adc_cali_curve_fitting_config_t cal = {
        .unit_id = unit, .chan = s_channel, .atten = ADC_ATTEN_DB_12, .bitwidth = ADC_BITWIDTH_12,
    };
    esp_err_t error = adc_cali_create_scheme_curve_fitting(&cal, &s_calibration);
    if (error != ESP_OK) {
        s_calibration = NULL;
        ESP_LOGW(TAG, "ADC calibration unavailable (%s); reporting raw counts only", esp_err_to_name(error));
    }
    ESP_LOGI(TAG, "Relay GPIO%d OFF; MQ135 GPIO%d; warm-up %ds; good<=%d bad>=%d very_bad>=%d",
        relay, sensor, CONFIG_AP_WARMUP_SEC, CONFIG_AP_GOOD_RAW, CONFIG_AP_BAD_RAW, CONFIG_AP_VERY_BAD_RAW);
    ESP_LOGI(TAG, "MQ135 ppm estimate: Vc=%dmV divider=%d/1000 RL=%dohm R0=%dohm (reference curve)",
        CONFIG_AP_MQ135_SUPPLY_MV, CONFIG_AP_MQ135_DIVIDER_MILLI,
        CONFIG_AP_MQ135_RL_OHM, CONFIG_AP_MQ135_R0_OHM);
    return ESP_OK;
}

esp_err_t ap_read_sensor(int *raw, int *adc_mv)
{
    if (!s_adc || !raw || !adc_mv) return ESP_ERR_INVALID_STATE;
    *raw = -1; *adc_mv = -1;
    int sum = 0;
    for (int i = 0; i < 16; ++i) {
        int value;
        esp_err_t error = adc_oneshot_read(s_adc, s_channel, &value);
        if (error != ESP_OK) return error;
        sum += value;
        vTaskDelay(pdMS_TO_TICKS(1));
    }
    *raw = (sum + 8) / 16;
    if (*raw <= 0 || *raw >= 4095) return ESP_ERR_INVALID_RESPONSE;
    if (s_calibration && adc_cali_raw_to_voltage(s_calibration, *raw, adc_mv) != ESP_OK)
        *adc_mv = -1;
    return ESP_OK;
}
