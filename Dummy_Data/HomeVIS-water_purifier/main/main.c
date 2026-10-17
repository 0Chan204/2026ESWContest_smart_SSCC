#include <inttypes.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <strings.h>
#include <time.h>

#include "freertos/FreeRTOS.h"
#include "freertos/event_groups.h"
#include "freertos/queue.h"
#include "freertos/task.h"
#include "esp_console.h"
#include "esp_event.h"
#include "esp_log.h"
#include "esp_mac.h"
#include "esp_netif.h"
#include "esp_netif_sntp.h"
#include "esp_timer.h"
#include "esp_wifi.h"
#include "mqtt_client.h"
#include "nvs_flash.h"
#include "sdkconfig.h"
#include "water_model.h"

#define DEVICE_ID "water-01"
#define TOPIC_PREFIX "home/kitchen/water_purifier/" DEVICE_ID

#define WIFI_READY BIT0
#define MQTT_READY BIT1
#define STATE_INTERVAL_US INT64_C(5000000)
#define ACK_CACHE_SIZE 8

typedef struct {
    water_command_t command;
    const char *error;
    bool show_status;
} water_request_t;

typedef struct {
    char command_id[WATER_COMMAND_ID_SIZE];
    char *payload;
} cached_ack_t;

static const char *TAG = "water_purifier_dummy";
static EventGroupHandle_t s_events;
static QueueHandle_t s_requests;
static esp_mqtt_client_handle_t s_mqtt;
static char s_client_id[48];
/* MQTT callbacks run serially on the MQTT task. */
static char s_rx[WATER_MAX_COMMAND_SIZE + 1];
static int s_rx_expected;
static int s_rx_used;
static int s_subscription_id = -1;

static bool enqueue_payload(const char *topic, const char *payload, int qos)
{
    if (!(xEventGroupGetBits(s_events) & MQTT_READY)) {
        return false;
    }
    /* Keep the state task responsive while the network is slow. */
    if (qos == 0 && esp_mqtt_client_get_outbox_size(s_mqtt) > 8192) {
        return false;
    }
    const int id = esp_mqtt_client_enqueue(s_mqtt, topic, payload, 0, qos, 0, true);
    if (id < 0) {
        ESP_LOGW(TAG, "MQTT outbox rejected %s (%d)", topic, id);
        return false;
    }
    ESP_LOGI(TAG, "TX %s %s", topic, payload);
    return true;
}

static char *make_ack(const char *command_id, const char *error,
                      const water_state_t *state, const char *timestamp)
{
    cJSON *root = cJSON_CreateObject();
    if (!root) {
        return NULL;
    }
    char *payload = NULL;
    if (!cJSON_AddStringToObject(root, "commandId", command_id) ||
        !cJSON_AddStringToObject(root, "result", error ? "rejected" : "applied") ||
        !cJSON_AddStringToObject(root, "appliedAt", timestamp) ||
        (error && !cJSON_AddStringToObject(root, "reason", error))) {
        goto done;
    }
    if (state) {
        cJSON *snapshot = water_state_json(state, timestamp);
        if (!snapshot || !cJSON_AddItemToObject(root, "state", snapshot)) {
            cJSON_Delete(snapshot);
            goto done;
        }
    }
    payload = cJSON_PrintUnformatted(root);
done:
    cJSON_Delete(root);
    return payload;
}

static bool publish_state(const water_state_t *state, const char *timestamp)
{
    cJSON *root = water_state_json(state, timestamp);
    char *payload = root ? cJSON_PrintUnformatted(root) : NULL;
    const bool sent = payload && enqueue_payload(TOPIC_PREFIX "/state", payload, 0);
    cJSON_free(payload);
    cJSON_Delete(root);
    return sent;
}

static void state_task(void *arg)
{
    (void)arg;
    water_state_t state = {0};
    cached_ack_t cache[ACK_CACHE_SIZE] = {0};
    unsigned next_cache = 0;
    int64_t last_report_us = 0;
    bool pending = true;
    bool was_ready = false;
    while (true) {
        water_request_t request;
        const bool received = xQueueReceive(s_requests, &request, pdMS_TO_TICKS(50)) == pdTRUE;
        const int64_t now_us = esp_timer_get_time();
        pending |= water_tick(&state, now_us);
        char timestamp[32];
        const bool clock_ready = water_timestamp(time(NULL), timestamp);
        const bool ready = clock_ready && (xEventGroupGetBits(s_events) & MQTT_READY);
        if (ready && !was_ready) {
            pending = true;
        }
        was_ready = ready;

        if (received && request.show_status) {
            ESP_LOGI(TAG, "%s: status=%s lastDispensedMl=%d MQTT=%s clock=%s", DEVICE_ID,
                     state.dispensing ? "dispensing" : "idle",
                     state.has_last_amount ? state.last_dispensed_ml : -1,
                     ready ? "ready" : "not ready", clock_ready ? "synced" : "waiting for NTP");
        } else if (received) {
            const water_command_t *command = &request.command;
            const char *previous_ack = NULL;
            if (!command->local && !request.error) {
                for (unsigned i = 0; i < ACK_CACHE_SIZE; ++i) {
                    if (cache[i].payload && strcmp(cache[i].command_id, command->command_id) == 0) {
                        previous_ack = cache[i].payload;
                        break;
                    }
                }
            }
            if (previous_ack) {
                /* QoS 1 redelivery must never dispense a second portion. */
                enqueue_payload(TOPIC_PREFIX "/ack", previous_ack, 1);
            } else {
                if (!request.error) {
                    request.error = water_apply(&state, command, now_us, CONFIG_WATER_FLOW_ML_SEC);
                    if (!request.error) {
                        pending = true;
                        ESP_LOGI(TAG, "%s: status=%s (%s)", DEVICE_ID,
                                 state.dispensing ? "dispensing" : "idle",
                                 command->local ? "console" : "api");
                    } else {
                        ESP_LOGW(TAG, "Command rejected: %s", request.error);
                    }
                }
                if (!command->local && clock_ready && command->command_id[0]) {
                    char *ack = make_ack(command->command_id, request.error, &state, timestamp);
                    if (ack) {
                        enqueue_payload(TOPIC_PREFIX "/ack", ack, 1);
                        if (!request.error) {
                            cached_ack_t *entry = &cache[next_cache++ % ACK_CACHE_SIZE];
                            cJSON_free(entry->payload);
                            entry->payload = ack;
                            snprintf(entry->command_id, sizeof(entry->command_id), "%s", command->command_id);
                        } else {
                            cJSON_free(ack);
                        }
                    } else {
                        ESP_LOGE(TAG, "Unable to allocate ACK");
                    }
                }
            }
        }
        if (ready && (pending || now_us - last_report_us >= STATE_INTERVAL_US)) {
            if (publish_state(&state, timestamp)) {
                pending = false;
                last_report_us = now_us;
            }
        }
    }
}

static int console_command(int argc, char **argv)
{
    if (argc != 1) {
        printf("Usage: on | off | status\n");
        return 1;
    }
    water_request_t request = {0};
    if (strcmp(argv[0], "status") == 0) {
        request.show_status = true;
    } else {
        request.command.local = true;
        request.command.action = strcasecmp(argv[0], "on") == 0 ? WATER_DISPENSE : WATER_STOP;
        request.command.amount_ml = CONFIG_WATER_CONSOLE_AMOUNT_ML;
        snprintf(request.command.command_id, sizeof(request.command.command_id),
                 "local-%s-%" PRId64, s_client_id, esp_timer_get_time());
    }
    if (xQueueSend(s_requests, &request, 0) != pdTRUE) {
        printf("Command queue full; retry.\n");
        return 1;
    }
    return 0;
}

static void console_start(void)
{
    esp_console_repl_t *repl = NULL;
    esp_console_repl_config_t config = ESP_CONSOLE_REPL_CONFIG_DEFAULT();
    config.prompt = DEVICE_ID "> ";
    config.max_cmdline_length = 64;
#if defined(CONFIG_ESP_CONSOLE_UART_DEFAULT) || defined(CONFIG_ESP_CONSOLE_UART_CUSTOM)
    esp_console_dev_uart_config_t device = ESP_CONSOLE_DEV_UART_CONFIG_DEFAULT();
    ESP_ERROR_CHECK(esp_console_new_repl_uart(&device, &config, &repl));
#elif defined(CONFIG_ESP_CONSOLE_USB_CDC)
    esp_console_dev_usb_cdc_config_t device = ESP_CONSOLE_DEV_CDC_CONFIG_DEFAULT();
    ESP_ERROR_CHECK(esp_console_new_repl_usb_cdc(&device, &config, &repl));
#elif defined(CONFIG_ESP_CONSOLE_USB_SERIAL_JTAG)
    esp_console_dev_usb_serial_jtag_config_t device = ESP_CONSOLE_DEV_USB_SERIAL_JTAG_CONFIG_DEFAULT();
    ESP_ERROR_CHECK(esp_console_new_repl_usb_serial_jtag(&device, &config, &repl));
#else
#error "Select UART, USB CDC, or USB Serial/JTAG as the primary console in menuconfig"
#endif
    ESP_ERROR_CHECK(esp_console_register_help_command());
    const char *names[] = {"on", "off", "On", "Off", "ON", "OFF", "status"};
    for (size_t i = 0; i < sizeof(names) / sizeof(names[0]); ++i) {
        const esp_console_cmd_t command = {
            .command = names[i],
            .help = "on: dispense configured mL; off: stop; status: show state (no arguments)",
            .func = console_command,
        };
        ESP_ERROR_CHECK(esp_console_cmd_register(&command));
    }
    ESP_ERROR_CHECK(esp_console_start_repl(repl));
}

static void mqtt_receive(esp_mqtt_event_handle_t event)
{
    if (event->current_data_offset == 0) {
        s_rx_expected = 0;
        s_rx_used = 0;
        /* Old retained commands must not be reapplied on boot/reconnect. */
        if (event->retain || event->topic_len != (int)strlen(TOPIC_PREFIX "/command") ||
            !event->topic || memcmp(event->topic, TOPIC_PREFIX "/command", event->topic_len) != 0 ||
            event->total_data_len <= 0 || event->total_data_len > WATER_MAX_COMMAND_SIZE) {
            ESP_LOGW(TAG, "Ignoring retained, oversized, empty, or unexpected-topic command");
            return;
        }
        s_rx_expected = event->total_data_len;
    }
    if (s_rx_expected == 0) {
        return;
    }
    if (event->current_data_offset != s_rx_used || event->data_len <= 0 ||
        event->total_data_len != s_rx_expected || event->data_len > s_rx_expected - s_rx_used) {
        s_rx_expected = 0;
        ESP_LOGW(TAG, "Discarding inconsistent MQTT fragments");
        return;
    }
    memcpy(s_rx + s_rx_used, event->data, event->data_len);
    s_rx_used += event->data_len;
    if (s_rx_used != s_rx_expected) {
        return;
    }
    s_rx[s_rx_used] = '\0';
    s_rx_expected = 0;
    water_request_t request = {0};
    request.error = water_parse_command(s_rx, s_rx_used, DEVICE_ID, &request.command);
    if (request.error) {
        ESP_LOGW(TAG, "Rejected command: %s", request.error);
    }
    if (xQueueSend(s_requests, &request, 0) != pdTRUE) {
        ESP_LOGW(TAG, "Command queue full");
        char timestamp[32];
        if (request.command.command_id[0] && water_timestamp(time(NULL), timestamp)) {
            char *ack = make_ack(request.command.command_id, "busy", NULL, timestamp);
            if (ack) {
                enqueue_payload(TOPIC_PREFIX "/ack", ack, 1);
                cJSON_free(ack);
            }
        }
    }
}

static void mqtt_event(void *arg, esp_event_base_t base, int32_t id, void *data)
{
    (void)arg;
    (void)base;
    esp_mqtt_event_handle_t event = data;
    switch ((esp_mqtt_event_id_t)id) {
    case MQTT_EVENT_CONNECTED:
        s_subscription_id = esp_mqtt_client_subscribe(event->client, TOPIC_PREFIX "/command", 1);
        ESP_LOGI(TAG, "MQTT connected; subscribing to %s/command", TOPIC_PREFIX);
        if (s_subscription_id < 0) {
            ESP_LOGE(TAG, "Subscribe failed; reconnecting");
            ESP_ERROR_CHECK_WITHOUT_ABORT(esp_mqtt_client_reconnect(event->client));
        }
        break;
    case MQTT_EVENT_SUBSCRIBED:
        if (event->msg_id == s_subscription_id) {
            if (event->error_handle &&
                event->error_handle->error_type == MQTT_ERROR_TYPE_SUBSCRIBE_FAILED) {
                xEventGroupClearBits(s_events, MQTT_READY);
                ESP_LOGE(TAG, "Broker rejected command subscription; check the topic ACL");
            } else {
                xEventGroupSetBits(s_events, MQTT_READY);
            }
        }
        break;
    case MQTT_EVENT_DISCONNECTED:
        xEventGroupClearBits(s_events, MQTT_READY);
        s_rx_expected = 0;
        ESP_LOGW(TAG, "MQTT disconnected; reconnecting automatically");
        break;
    case MQTT_EVENT_DATA:
        mqtt_receive(event);
        break;
    case MQTT_EVENT_ERROR:
        ESP_LOGE(TAG, "MQTT error type=%d", event->error_handle ? event->error_handle->error_type : -1);
        break;
    default:
        break;
    }
}

static void wifi_event(void *arg, esp_event_base_t base, int32_t id, void *data)
{
    (void)arg;
    if (base == WIFI_EVENT && (id == WIFI_EVENT_STA_START || id == WIFI_EVENT_STA_DISCONNECTED)) {
        xEventGroupClearBits(s_events, WIFI_READY | MQTT_READY);
        if (id == WIFI_EVENT_STA_DISCONNECTED) {
            ESP_LOGW(TAG, "Wi-Fi disconnected; reconnecting");
        }
        ESP_ERROR_CHECK_WITHOUT_ABORT(esp_wifi_connect());
    } else if (base == IP_EVENT && id == IP_EVENT_STA_GOT_IP) {
        const ip_event_got_ip_t *event = data;
        ESP_LOGI(TAG, "Wi-Fi ready: " IPSTR, IP2STR(&event->ip_info.ip));
        xEventGroupSetBits(s_events, WIFI_READY);
    }
}

static bool configuration_valid(void)
{
    const size_t ssid = strlen(CONFIG_WATER_WIFI_SSID);
    const size_t password = strlen(CONFIG_WATER_WIFI_PASSWORD);
    if (ssid == 0 || ssid > 32 || (password != 0 && (password < 8 || password > 63))) {
        ESP_LOGE(TAG, "Set Wi-Fi SSID (1-32 bytes) and password (8-63 bytes, or empty) in menuconfig");
        return false;
    }
    if (!CONFIG_WATER_MQTT_HOST[0] || strpbrk(CONFIG_WATER_MQTT_HOST, "/: \t\r\n") ||
        !CONFIG_WATER_NTP_SERVER[0]) {
        ESP_LOGE(TAG, "Set a broker hostname/IPv4 without scheme or port, and an NTP server");
        return false;
    }
    return true;
}

void app_main(void)
{
    esp_err_t error = nvs_flash_init();
    if (error == ESP_ERR_NVS_NO_FREE_PAGES || error == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        ESP_ERROR_CHECK(nvs_flash_erase());
        error = nvs_flash_init();
    }
    ESP_ERROR_CHECK(error);
    s_events = xEventGroupCreate();
    s_requests = xQueueCreate(16, sizeof(water_request_t));
    if (!s_events || !s_requests) {
        abort();
    }
    uint8_t mac[6];
    ESP_ERROR_CHECK(esp_read_mac(mac, ESP_MAC_WIFI_STA));
    snprintf(s_client_id, sizeof(s_client_id), "%s-%02x%02x%02x%02x%02x%02x",
             DEVICE_ID, mac[0], mac[1], mac[2], mac[3], mac[4], mac[5]);
    if (xTaskCreate(state_task, "water_state", 6144, NULL, 5, NULL) != pdPASS) {
        abort();
    }
    console_start();
    ESP_LOGI(TAG, "Dummy water purifier: %s; type on, off, status, or help. No GPIO is driven.", TOPIC_PREFIX);
    if (!configuration_valid()) {
        ESP_LOGW(TAG, "Console remains available. Configure network settings and rebuild to enable MQTT.");
        return;
    }

    ESP_ERROR_CHECK(esp_netif_init());
    ESP_ERROR_CHECK(esp_event_loop_create_default());
    if (!esp_netif_create_default_wifi_sta()) {
        abort();
    }
    const wifi_init_config_t init = WIFI_INIT_CONFIG_DEFAULT();
    ESP_ERROR_CHECK(esp_wifi_init(&init));
    ESP_ERROR_CHECK(esp_event_handler_register(WIFI_EVENT, ESP_EVENT_ANY_ID, wifi_event, NULL));
    ESP_ERROR_CHECK(esp_event_handler_register(IP_EVENT, IP_EVENT_STA_GOT_IP, wifi_event, NULL));
    wifi_config_t wifi = {0};
    memcpy(wifi.sta.ssid, CONFIG_WATER_WIFI_SSID, strlen(CONFIG_WATER_WIFI_SSID));
    memcpy(wifi.sta.password, CONFIG_WATER_WIFI_PASSWORD, strlen(CONFIG_WATER_WIFI_PASSWORD));
    wifi.sta.threshold.authmode = CONFIG_WATER_WIFI_PASSWORD[0] ? WIFI_AUTH_WPA2_PSK : WIFI_AUTH_OPEN;
    wifi.sta.pmf_cfg.capable = true;
    ESP_ERROR_CHECK(esp_wifi_set_storage(WIFI_STORAGE_RAM));
    ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_STA));
    ESP_ERROR_CHECK(esp_wifi_set_config(WIFI_IF_STA, &wifi));
    ESP_ERROR_CHECK(esp_wifi_start());
    xEventGroupWaitBits(s_events, WIFI_READY, pdFALSE, pdTRUE, portMAX_DELAY);

    const esp_sntp_config_t ntp = ESP_NETIF_SNTP_DEFAULT_CONFIG(CONFIG_WATER_NTP_SERVER);
    ESP_ERROR_CHECK(esp_netif_sntp_init(&ntp));
    while (esp_netif_sntp_sync_wait(pdMS_TO_TICKS(10000)) != ESP_OK) {
        ESP_LOGW(TAG, "Waiting for NTP before starting MQTT; console input is available");
    }
    ESP_LOGI(TAG, "Clock synchronized; MQTT broker=%s:%d", CONFIG_WATER_MQTT_HOST, CONFIG_WATER_MQTT_PORT);
    const esp_mqtt_client_config_t mqtt = {
        .broker.address.hostname = CONFIG_WATER_MQTT_HOST,
        .broker.address.port = CONFIG_WATER_MQTT_PORT,
        .broker.address.transport = MQTT_TRANSPORT_OVER_TCP,
        .credentials.client_id = s_client_id,
        .credentials.username = CONFIG_WATER_MQTT_USERNAME[0] ? CONFIG_WATER_MQTT_USERNAME : NULL,
        .credentials.authentication.password = CONFIG_WATER_MQTT_PASSWORD[0] ? CONFIG_WATER_MQTT_PASSWORD : NULL,
        .session.protocol_ver = MQTT_PROTOCOL_V_3_1_1,
        .network.reconnect_timeout_ms = 5000,
        .network.timeout_ms = 5000,
        .buffer.size = 512,
        .outbox.limit = 16384,
    };
    s_mqtt = esp_mqtt_client_init(&mqtt);
    if (!s_mqtt) {
        abort();
    }
    ESP_ERROR_CHECK(esp_mqtt_client_register_event(s_mqtt, MQTT_EVENT_ANY, mqtt_event, NULL));
    ESP_ERROR_CHECK(esp_mqtt_client_start(s_mqtt));
}
