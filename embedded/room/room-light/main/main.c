#include "light_model.h"
#include "light_network.h"
#include "light_output.h"

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
    char id[RL_COMMAND_ID_SIZE];
    const char *result;
    const char *reason;
    char timestamp[32];
    rl_state_t snapshot;
} ack_record_t;

static const char *TAG = "room_light_control";
static rl_state_t s_state;
static ack_record_t s_history[HISTORY_SIZE];
static unsigned s_history_cursor;
static bool s_dirty = true;

static ack_record_t *find_ack(const char *id)
{
    for (int i = 0; i < HISTORY_SIZE; ++i)
        if (s_history[i].valid && !strcmp(s_history[i].id, id))
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

static void process_request(const rl_request_t *request, int64_t now_us)
{
    rl_command_t command;
    const char *error = rl_parse(request->payload, request->length, &command);
    if (!command.id[0]) {
        ESP_LOGW(TAG, "Ignoring command without usable commandId: %s", error ? error : "invalid envelope");
        return;
    }
    ack_record_t *cached = find_ack(command.id);
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
    if (!rl_timestamp(time(NULL), timestamp)) return;
    const char *result = "rejected";
    if (!error) {
        rl_state_t candidate = s_state;
        error = rl_apply(&candidate, &command, now_us);
        if (!error) {
            esp_err_t hardware = rl_output_light(candidate.light.brightness);
            if (hardware == ESP_OK) {
                s_state = candidate;
                s_dirty = true;
                result = "applied";
            } else {
                result = "failed";
                error = "hardware_error";
                ESP_LOGE(TAG, "Command hardware failure: %s", esp_err_to_name(hardware));
            }
        }
    }
    *record = (ack_record_t) {
        .valid = true, .pending = true,
        .result = result, .reason = error, .snapshot = s_state,
    };
    snprintf(record->id, sizeof(record->id), "%s", command.id);
    snprintf(record->timestamp, sizeof(record->timestamp), "%s", timestamp);
    ESP_LOGI(TAG, "Light command %s: %s%s%s",
             command.id, result, error ? ": " : "", error ? error : "");
    ESP_LOGI(TAG, "Light output: power=%s brightness=%d%%",
             s_state.light.power ? "on" : "off", s_state.light.brightness);
}

static void flush_acks(void)
{
    for (int i = 0; i < HISTORY_SIZE; ++i) {
        ack_record_t *record = &s_history[i];
        if (!record->pending) continue;
        cJSON *root = rl_ack_json(record->id, record->result,
                                   record->reason, &record->snapshot, record->timestamp);
        if (!rl_publish(true, root)) break;
        record->pending = false;
    }
}

void app_main(void)
{
    /* Initialize all eight LEDs OFF before starting Wi-Fi or MQTT. */
    ESP_ERROR_CHECK(rl_output_init());
    ESP_LOGI(TAG, "Light starts OFF; waiting for on at " RL_TOPIC_BASE "/command");
    rl_requests = xQueueCreate(8, sizeof(rl_request_t));
    rl_network_events = xEventGroupCreate();
    configASSERT(rl_requests && rl_network_events);
    configASSERT(xTaskCreate(rl_network_task, "room_light_network", 6144, NULL, 5, NULL) == pdPASS);
    static rl_request_t request;
    int64_t next_report = 0;
    int64_t next_error_log = 0;
    bool was_online = false;
    for (;;) {
        int64_t now = esp_timer_get_time();
        rl_state_t candidate = s_state;
        if (rl_tick(&candidate, now)) {
            esp_err_t error = rl_output_light(candidate.light.brightness);
            if (error == ESP_OK) {
                s_state = candidate;
                s_dirty = true;
            } else if (now >= next_error_log) {
                ESP_LOGE(TAG, "Light animation output failed: %s", esp_err_to_name(error));
                next_error_log = now + 1000000;
            }
        }
        if (xQueueReceive(rl_requests, &request, 0) == pdTRUE)
            process_request(&request, now);
        bool online = (xEventGroupGetBits(rl_network_events) & RL_NETWORK_ONLINE) != 0;
        if (online) {
            if (!was_online) s_dirty = true;
            flush_acks();
            char timestamp[32];
            if (rl_timestamp(time(NULL), timestamp)) {
                if ((s_dirty || now >= next_report) &&
                    rl_publish(false, rl_state_json(&s_state, timestamp))) {
                    s_dirty = false;
                    next_report = now + REPORT_INTERVAL_US;
                }
            }
        }
        was_online = online;
        vTaskDelay(pdMS_TO_TICKS(20));
    }
}
