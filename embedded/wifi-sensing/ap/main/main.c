/* ESP32-C6 local AP for HomeVIS CSI receiver boards.
 * Receivers initiate gateway pings; lwIP replies automatically.
 * This AP does not collect CSI or initiate measurement traffic.
 */
#include <stdbool.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>

#include "freertos/FreeRTOS.h"
#include "freertos/event_groups.h"
#include "freertos/task.h"
#include "esp_event.h"
#include "esp_log.h"
#include "esp_mac.h"
#include "esp_netif.h"
#include "esp_wifi.h"
#include "led_strip.h"
#include "nvs_flash.h"

#if !CONFIG_IDF_TARGET_ESP32C6
#error "This firmware requires ESP32-C6."
#endif

#define RGB_LEVEL 8
#define AP_STARTED_BIT BIT0
#define EVER_CONNECTED_BIT BIT1

_Static_assert(CONFIG_HOMEVIS_AP_MAX_CONNECTIONS <= ESP_WIFI_MAX_CONN_NUM,
               "Too many AP clients");
_Static_assert(CONFIG_HOMEVIS_AP_MAX_CONNECTIONS + CONFIG_ESP_WIFI_ESPNOW_MAX_ENCRYPT_NUM <= 17,
               "SoftAP and ESP-NOW exceed the available encryption keys");

static const char *TAG = "homevis_ap";
static EventGroupHandle_t s_ap_events;
static led_strip_handle_t s_led;

static void rgb_set(uint8_t red, uint8_t green, uint8_t blue)
{
    ESP_ERROR_CHECK(led_strip_set_pixel(s_led, 0, red, green, blue));
    ESP_ERROR_CHECK(led_strip_refresh(s_led));
}

static void rgb_init(void)
{
    led_strip_config_t strip = {
        .strip_gpio_num = CONFIG_HOMEVIS_RGB_GPIO,
        .max_leds = 1,
        .led_model = LED_MODEL_WS2812,
        .color_component_format = LED_STRIP_COLOR_COMPONENT_FMT_GRB,
    };
    led_strip_rmt_config_t rmt = {
        .clk_src = RMT_CLK_SRC_DEFAULT,
        .resolution_hz = 10 * 1000 * 1000,
        .mem_block_symbols = 64,
    };
    ESP_ERROR_CHECK(led_strip_new_rmt_device(&strip, &rmt, &s_led));
    rgb_set(RGB_LEVEL, RGB_LEVEL, RGB_LEVEL);
}

static void wifi_event_handler(void *arg, esp_event_base_t base,
                               int32_t id, void *data)
{
    if (base == WIFI_EVENT && id == WIFI_EVENT_AP_START) {
        xEventGroupSetBits(s_ap_events, AP_STARTED_BIT);
        ESP_LOGI(TAG, "AP ready: SSID=%s, channel=%d, IP=192.168.4.1, max clients=%d",
                 CONFIG_HOMEVIS_AP_SSID, CONFIG_HOMEVIS_AP_CHANNEL,
                 CONFIG_HOMEVIS_AP_MAX_CONNECTIONS);
    } else if (base == WIFI_EVENT && id == WIFI_EVENT_AP_STOP) {
        xEventGroupClearBits(s_ap_events, AP_STARTED_BIT);
        ESP_LOGW(TAG, "AP stopped");
    } else if (base == WIFI_EVENT && id == WIFI_EVENT_AP_STACONNECTED) {
        const wifi_event_ap_staconnected_t *event = data;
        xEventGroupSetBits(s_ap_events, EVER_CONNECTED_BIT);
        ESP_LOGI(TAG, "Receiver connected: " MACSTR, MAC2STR(event->mac));
    } else if (base == WIFI_EVENT && id == WIFI_EVENT_AP_STADISCONNECTED) {
        const wifi_event_ap_stadisconnected_t *event = data;
        ESP_LOGW(TAG, "Receiver disconnected: " MACSTR, MAC2STR(event->mac));
    } else if (base == IP_EVENT && id == IP_EVENT_AP_STAIPASSIGNED) {
        const ip_event_ap_staipassigned_t *event = data;
        ESP_LOGI(TAG, "DHCP lease: " MACSTR " -> " IPSTR,
                 MAC2STR(event->mac), IP2STR(&event->ip));
    }
}

static void wifi_init_softap(void)
{
    const size_t ssid_len = strlen(CONFIG_HOMEVIS_AP_SSID);
    const size_t password_len = strlen(CONFIG_HOMEVIS_AP_PASSWORD);
    if (ssid_len == 0 || ssid_len > 32 || password_len < 8 || password_len > 63) {
        ESP_LOGE(TAG, "SSID must be 1-32 bytes; WPA2 password must be 8-63 bytes");
        abort();
    }
    esp_netif_t *ap_netif = esp_netif_create_default_wifi_ap();
    if (!ap_netif) {
        abort();
    }
    ESP_ERROR_CHECK(esp_netif_dhcps_stop(ap_netif));
    esp_netif_ip_info_t ip = {0};
    ip.ip.addr = ESP_IP4TOADDR(192, 168, 4, 1);
    ip.gw.addr = ESP_IP4TOADDR(192, 168, 4, 1);
    ip.netmask.addr = ESP_IP4TOADDR(255, 255, 255, 0);
    ESP_ERROR_CHECK(esp_netif_set_ip_info(ap_netif, &ip));
    ESP_ERROR_CHECK(esp_netif_dhcps_start(ap_netif));

    wifi_init_config_t init = WIFI_INIT_CONFIG_DEFAULT();
    ESP_ERROR_CHECK(esp_wifi_init(&init));
    ESP_ERROR_CHECK(esp_wifi_set_storage(WIFI_STORAGE_RAM));
    ESP_ERROR_CHECK(esp_event_handler_register(WIFI_EVENT, ESP_EVENT_ANY_ID,
                                              wifi_event_handler, NULL));
    ESP_ERROR_CHECK(esp_event_handler_register(IP_EVENT, IP_EVENT_AP_STAIPASSIGNED,
                                              wifi_event_handler, NULL));
    wifi_config_t config = {
        .ap = {
            .channel = CONFIG_HOMEVIS_AP_CHANNEL,
            .authmode = WIFI_AUTH_WPA2_PSK,
            .max_connection = CONFIG_HOMEVIS_AP_MAX_CONNECTIONS,
            .pmf_cfg = {.required = false},
        },
    };
    memcpy(config.ap.ssid, CONFIG_HOMEVIS_AP_SSID, ssid_len);
    config.ap.ssid_len = ssid_len;
    memcpy(config.ap.password, CONFIG_HOMEVIS_AP_PASSWORD, password_len);
    ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_AP));
    ESP_ERROR_CHECK(esp_wifi_set_config(WIFI_IF_AP, &config));
    /* Keep AP responses compatible with the receivers' legacy/HT20 CSI. */
    ESP_ERROR_CHECK(esp_wifi_set_protocol(WIFI_IF_AP,
                                        WIFI_PROTOCOL_11B | WIFI_PROTOCOL_11G | WIFI_PROTOCOL_11N));
    ESP_ERROR_CHECK(esp_wifi_set_bandwidth(WIFI_IF_AP, WIFI_BW_HT20));
    ESP_ERROR_CHECK(esp_wifi_start());
    ESP_ERROR_CHECK(esp_wifi_set_ps(WIFI_PS_NONE));
}

/* Only the main task writes the LED. The driver owns the client list. */
static void supervise(void)
{
    int previous_color = -1;
    for (;;) {
        EventBits_t bits = xEventGroupGetBits(s_ap_events);
        int color = 0;
        if (bits & AP_STARTED_BIT) {
            wifi_sta_list_t stations = {0};
            if (esp_wifi_ap_get_sta_list(&stations) == ESP_OK) {
                color = stations.num > 0 ? 2 : (bits & EVER_CONNECTED_BIT) ? 0 : 1;
            }
        }
        if (color != previous_color) {
            rgb_set(color != 2 ? RGB_LEVEL : 0, color != 0 ? RGB_LEVEL : 0, 0);
            previous_color = color;
        }
        vTaskDelay(pdMS_TO_TICKS(500));
    }
}

void app_main(void)
{
    rgb_init();
    s_ap_events = xEventGroupCreate();
    if (!s_ap_events) {
        ESP_LOGE(TAG, "Cannot allocate AP event group");
        abort();
    }
    esp_err_t err = nvs_flash_init();
    if (err == ESP_ERR_NVS_NO_FREE_PAGES || err == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        ESP_ERROR_CHECK(nvs_flash_erase());
        err = nvs_flash_init();
    }
    ESP_ERROR_CHECK(err);
    ESP_ERROR_CHECK(esp_netif_init());
    ESP_ERROR_CHECK(esp_event_loop_create_default());
    wifi_init_softap();
    ESP_LOGI(TAG, "AP only: connect up to %d receivers to %s; CSI is collected on receivers",
             CONFIG_HOMEVIS_AP_MAX_CONNECTIONS, CONFIG_HOMEVIS_AP_SSID);
    supervise();
}
