#include "device_model.h"
#include "device_network.h"
#include "device_output.h"

#include <stdio.h>
#include <string.h>
#include "esp_log.h"
#include "esp_timer.h"
#include "freertos/task.h"

#define HISTORY_SIZE 32
#define REPORT_INTERVAL_US INT64_C(5000000)

typedef struct {
    bool valid;
    bool pending;
    klh_device_t device;
    char id[KLH_COMMAND_ID_SIZE];
    const char *result;
    const char *reason;
    char timestamp[32];
    klh_state_t snapshot;
} ack_record_t;

static const char *TAG = "kitchen_control";
static klh_state_t s_state;
static ack_record_t s_history[HISTORY_SIZE];
static unsigned s_history_cursor;
static bool s_dirty[2] = {true, true};

static ack_record_t *find_ack(klh_device_t device, const char *id)
{
    for (int i = 0; i < HISTORY_SIZE; ++i)
        if (s_history[i].valid && s_history[i].device == device && !strcmp(s_history[i].id, id))
            return &s_history[i];
    return NULL;
}

static ack_record_t *reserve_ack(void)
{
    for (unsigned i = 0; i < HISTORY_SIZE; ++i) {
        unsigned index = (s_history_cursor + i) % HISTORY_SIZE;
        if (!s_history[index].pending) {
            s_history_cursor = (index + 1) % HISTORY_SIZE;
            return &s_history[index];
        }
    }
    return NULL;
}

static void process_request(const klh_request_t *request, int64_t now_us)
{
    klh_command_t command;
    const char *error = klh_parse(request->device, request->payload, request->length, &command);
    if (!command.id[0]) {
        ESP_LOGW(TAG, "Ignoring command without usable commandId: %s", error ? error : "invalid envelope");
        return;
    }
    ack_record_t *cached = find_ack(request->device, command.id);
    if (cached) {
        /* A QoS 1 retransmission must not restart a blink or fade timer. */
        cached->pending = true;
        return;
    }
    ack_record_t *record = reserve_ack();
    if (!record) {
        ESP_LOGE(TAG, "ACK history full of pending replies; command not executed");
        return;
    }
    char timestamp[32];
    if (!klh_timestamp(time(NULL), timestamp)) return;
    const char *result = "rejected";
    if (!error) {
        klh_state_t candidate = s_state;
        error = klh_apply(&candidate, &command, now_us);
        if (!error) {
            esp_err_t hardware = command.device == KLH_LIGHT ?
                klh_output_light(candidate.light.brightness) : klh_output_fan(candidate.fan_power);
            if (hardware == ESP_OK) {
                s_state = candidate;
                s_dirty[command.device] = true;
                result = "applied";
            } else {
                result = "failed";
                error = "hardware_error";
                ESP_LOGE(TAG, "Command hardware failure: %s", esp_err_to_name(hardware));
            }
        }
    }
    *record = (ack_record_t) {
        .valid = true, .pending = true, .device = command.device,
        .result = result, .reason = error, .snapshot = s_state,
    };
    snprintf(record->id, sizeof(record->id), "%s", command.id);
    snprintf(record->timestamp, sizeof(record->timestamp), "%s", timestamp);
    ESP_LOGI(TAG, "%s command %s: %s%s%s", command.device == KLH_LIGHT ? "light" : "fan",
             command.id, result, error ? ": " : "", error ? error : "");
}

static void flush_acks(void)
{
    for (int i = 0; i < HISTORY_SIZE; ++i) {
        ack_record_t *record = &s_history[i];
        if (!record->pending) continue;
        cJSON *root = klh_ack_json(record->device, record->id, record->result,
                                   record->reason, &record->snapshot, record->timestamp);
        if (!klh_publish(record->device, true, root)) break;
        record->pending = false;
    }
}

void app_main(void)
{
    /* Initialize the relay and LEDs OFF before starting Wi-Fi or MQTT. */
    ESP_ERROR_CHECK(klh_output_init());
    klh_requests = xQueueCreate(8, sizeof(klh_request_t));
    klh_network_events = xEventGroupCreate();
    configASSERT(klh_requests && klh_network_events);
    configASSERT(xTaskCreate(klh_network_task, "kitchen_network", 6144, NULL, 5, NULL) == pdPASS);
    static klh_request_t request;
    int64_t next_report[2] = {0, 0};
    int64_t next_error_log = 0;
    bool was_online = false;
    for (;;) {
        int64_t now = esp_timer_get_time();
        klh_state_t candidate = s_state;
        if (klh_tick(&candidate, now)) {
            esp_err_t error = klh_output_light(candidate.light.brightness);
            if (error == ESP_OK) {
                s_state = candidate;
                s_dirty[KLH_LIGHT] = true;
            } else if (now >= next_error_log) {
                ESP_LOGE(TAG, "Light animation output failed: %s", esp_err_to_name(error));
                next_error_log = now + 1000000;
            }
        }
        if (xQueueReceive(klh_requests, &request, 0) == pdTRUE)
            process_request(&request, now);
        bool online = (xEventGroupGetBits(klh_network_events) & KLH_NETWORK_ONLINE) != 0;
        if (online) {
            if (!was_online) s_dirty[KLH_LIGHT] = s_dirty[KLH_FAN] = true;
            flush_acks();
            char timestamp[32];
            if (klh_timestamp(time(NULL), timestamp)) {
                for (int device = KLH_LIGHT; device <= KLH_FAN; ++device) {
                    if ((s_dirty[device] || now >= next_report[device]) &&
                        klh_publish(device, false, klh_state_json(device, &s_state, timestamp))) {
                        s_dirty[device] = false;
                        next_report[device] = now + REPORT_INTERVAL_US;
                    }
                }
            }
        }
        was_online = online;
        vTaskDelay(pdMS_TO_TICKS(20));
    }
}
