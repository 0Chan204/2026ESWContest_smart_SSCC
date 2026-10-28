#include "water_network.h"

#include <stdio.h>
#include <string.h>
#include "sdkconfig.h"
#include "esp_crt_bundle.h"
#include "esp_event.h"
#include "esp_log.h"
#include "esp_netif.h"
#include "esp_netif_sntp.h"
#include "esp_timer.h"
#include "esp_wifi.h"
#include "mqtt_client.h"
#include "nvs_flash.h"
#include "freertos/task.h"

QueueHandle_t wp_requests;
EventGroupHandle_t wp_network_events;
static const char *TAG = "kitchen_water_network";
static esp_mqtt_client_handle_t s_mqtt;
static EventGroupHandle_t s_wifi_events;
#define WIFI_UP BIT0
static int s_water_subscription;

static void mqtt_event(void *arg, esp_event_base_t base, int32_t id, void *data)
{
    esp_mqtt_event_handle_t event = data;
    static wp_request_t request;
    static int used;
    static bool accepting;
    if (id == MQTT_EVENT_CONNECTED) {
        s_water_subscription = esp_mqtt_client_subscribe(s_mqtt, WP_TOPIC_BASE "/command", 1);
        ESP_LOGI(TAG, "MQTT connected; subscribing to water purifier commands");
    } else if (id == MQTT_EVENT_SUBSCRIBED) {
        if (event->msg_id == s_water_subscription)
            xEventGroupSetBits(wp_network_events, WP_NETWORK_ONLINE);
    } else if (id == MQTT_EVENT_DISCONNECTED) {
        xEventGroupClearBits(wp_network_events, WP_NETWORK_ONLINE);
        accepting = false;
        ESP_LOGW(TAG, "MQTT disconnected");
    } else if (id == MQTT_EVENT_DATA) {
        if (event->current_data_offset == 0) {
            accepting = false;
            used = 0;
            request.received_us = esp_timer_get_time();
            bool target = event->topic && event->topic_len == strlen(WP_TOPIC_BASE "/command") &&
                         !memcmp(event->topic, WP_TOPIC_BASE "/command", event->topic_len);
            if (target && !event->retain && event->total_data_len > 0 &&
                event->total_data_len <= WP_MAX_PAYLOAD) {
                accepting = true;
                request.length = event->total_data_len;
            } else {
                ESP_LOGW(TAG, "Ignoring retained, oversized, or unexpected MQTT command");
            }
        }
        if (!accepting) return;
        if (event->current_data_offset != used || event->data_len < 0 ||
            event->data_len > (int)request.length - used) {
            accepting = false;
            return;
        }
        memcpy(request.payload + used, event->data, event->data_len);
        used += event->data_len;
        if (used == request.length) {
            request.payload[used] = '\0';
            accepting = false;
            if (xQueueSend(wp_requests, &request, pdMS_TO_TICKS(50)) != pdTRUE)
                ESP_LOGE(TAG, "Command queue full; command not executed, retry with the same commandId");
        }
    } else if (id == MQTT_EVENT_ERROR) {
        ESP_LOGW(TAG, "MQTT transport error; check broker URI, credentials, and network");
    }
}

bool wp_publish(bool ack, cJSON *root)
{
    if (!root) return false;
    bool sent = false;
    if (s_mqtt && (xEventGroupGetBits(wp_network_events) & WP_NETWORK_ONLINE) &&
        (ack || esp_mqtt_client_get_outbox_size(s_mqtt) < 8192)) {
        char *payload = cJSON_PrintUnformatted(root);
        const char *topic = ack ? WP_TOPIC_BASE "/ack" : WP_TOPIC_BASE "/state";
        if (payload) sent = esp_mqtt_client_enqueue(s_mqtt, topic, payload, 0, 1, false, true) >= 0;
        cJSON_free(payload);
    }
    cJSON_Delete(root);
    return sent;
}

static void wifi_event(void *arg, esp_event_base_t base, int32_t id, void *data)
{
    if (base == IP_EVENT && id == IP_EVENT_STA_GOT_IP) {
        xEventGroupSetBits(s_wifi_events, WIFI_UP);
    } else if (base == WIFI_EVENT && id == WIFI_EVENT_STA_DISCONNECTED) {
        xEventGroupClearBits(s_wifi_events, WIFI_UP);
        xEventGroupClearBits(wp_network_events, WP_NETWORK_ONLINE);
    }
}

static esp_err_t init_wifi(void)
{
    esp_err_t error = nvs_flash_init();
    if (error == ESP_ERR_NVS_NO_FREE_PAGES || error == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        ESP_ERROR_CHECK(nvs_flash_erase());
        error = nvs_flash_init();
    }
    if (error != ESP_OK) return error;
#define TRY(call) do { error = (call); if (error != ESP_OK) return error; } while (0)
    TRY(esp_netif_init());
    TRY(esp_event_loop_create_default());
    if (!esp_netif_create_default_wifi_sta()) return ESP_ERR_NO_MEM;
    wifi_init_config_t init = WIFI_INIT_CONFIG_DEFAULT();
    TRY(esp_wifi_init(&init));
    TRY(esp_event_handler_register(WIFI_EVENT, WIFI_EVENT_STA_DISCONNECTED, wifi_event, NULL));
    TRY(esp_event_handler_register(IP_EVENT, IP_EVENT_STA_GOT_IP, wifi_event, NULL));
    if (strlen(CONFIG_WP_WIFI_SSID) > 32 || strlen(CONFIG_WP_WIFI_PASSWORD) > 63)
        return ESP_ERR_INVALID_ARG;
    wifi_config_t wifi = {0};
    memcpy(wifi.sta.ssid, CONFIG_WP_WIFI_SSID, strlen(CONFIG_WP_WIFI_SSID));
    memcpy(wifi.sta.password, CONFIG_WP_WIFI_PASSWORD, strlen(CONFIG_WP_WIFI_PASSWORD));
    wifi.sta.threshold.authmode = CONFIG_WP_WIFI_PASSWORD[0] ? WIFI_AUTH_WPA2_PSK : WIFI_AUTH_OPEN;
    TRY(esp_wifi_set_storage(WIFI_STORAGE_RAM));
    TRY(esp_wifi_set_mode(WIFI_MODE_STA));
    TRY(esp_wifi_set_config(WIFI_IF_STA, &wifi));
    esp_sntp_config_t sntp = ESP_NETIF_SNTP_DEFAULT_CONFIG(CONFIG_WP_NTP_SERVER);
    TRY(esp_netif_sntp_init(&sntp));
    TRY(esp_wifi_start());
    TRY(esp_wifi_set_ps(WIFI_PS_NONE));
    return ESP_OK;
#undef TRY
}

void wp_network_task(void *arg)
{
    if (!CONFIG_WP_WIFI_SSID[0] || !CONFIG_WP_MQTT_URI[0] || !CONFIG_WP_MQTT_CLIENT_ID[0]) {
        ESP_LOGW(TAG, "Configure Wi-Fi, MQTT URI and client ID in HomeVIS water purifier");
        vTaskDelete(NULL);
        return;
    }
    s_wifi_events = xEventGroupCreate();
    configASSERT(s_wifi_events);
    esp_err_t error = init_wifi();
    if (error != ESP_OK) {
        ESP_LOGE(TAG, "Wi-Fi initialization failed: %s", esp_err_to_name(error));
        vTaskDelete(NULL);
        return;
    }
    int64_t reconnect_at = 0;
    for (;;) {
        int64_t now = esp_timer_get_time();
        bool wifi_up = (xEventGroupGetBits(s_wifi_events) & WIFI_UP) != 0;
        if (!wifi_up && now >= reconnect_at) {
            esp_wifi_connect();
            reconnect_at = now + 5000000;
        }
        char timestamp[32];
        /* No commands or invented timestamps before the first successful SNTP sync. */
        if (!s_mqtt && wifi_up && wp_timestamp(time(NULL), timestamp)) {
            const esp_mqtt_client_config_t mqtt = {
                .broker.address.uri = CONFIG_WP_MQTT_URI,
                .broker.verification.crt_bundle_attach = esp_crt_bundle_attach,
                .credentials.client_id = CONFIG_WP_MQTT_CLIENT_ID,
                .credentials.username = CONFIG_WP_MQTT_USERNAME[0] ? CONFIG_WP_MQTT_USERNAME : NULL,
                .credentials.authentication.password = CONFIG_WP_MQTT_PASSWORD[0] ? CONFIG_WP_MQTT_PASSWORD : NULL,
                .network.reconnect_timeout_ms = 5000,
                .buffer.size = 512,
                .task.stack_size = 6144,
                .outbox.limit = 16384,
            };
            s_mqtt = esp_mqtt_client_init(&mqtt);
            if (s_mqtt) {
                ESP_ERROR_CHECK(esp_mqtt_client_register_event(s_mqtt, ESP_EVENT_ANY_ID, mqtt_event, NULL));
                ESP_ERROR_CHECK(esp_mqtt_client_start(s_mqtt));
            }
        }
        vTaskDelay(pdMS_TO_TICKS(250));
    }
}
