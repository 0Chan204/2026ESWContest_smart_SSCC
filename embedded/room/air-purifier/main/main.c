#include "air_model.h"
#include "air_network.h"
#include "air_hardware.h"

#include <stdio.h>
#include <string.h>
#include "esp_log.h"
#include "sdkconfig.h"
#include "esp_timer.h"
#include "freertos/task.h"

#define HISTORY_SIZE 32
#define REPORT_INTERVAL_US INT64_C(5000000)

typedef struct {
    bool valid;
    bool pending;
    char id[AP_COMMAND_ID_SIZE];
    const char *result;
    const char *reason;
    char timestamp[32];
    ap_state_t snapshot;
} ack_record_t;

static const char *TAG = "air_purifier_control";
static ap_state_t s_state;
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

static void process_request(const ap_request_t *request)
{
    ap_command_t command;
    const char *error = ap_parse(request->payload, request->length, &command);
    if (!command.id[0]) {
        ESP_LOGW(TAG, "Ignoring command without usable commandId: %s", error ? error : "invalid envelope");
        return;
    }
    ack_record_t *cached = find_ack(command.id);
    if (cached) {
        /* Replay the original result without executing a QoS 1 duplicate. */
        cached->pending = true;
        return;
    }
    ack_record_t *record = reserve_ack();
    if (!record) {
        ESP_LOGE(TAG, "ACK history full of pending replies; command not executed");
        return;
    }
    char timestamp[32];
    if (!ap_timestamp(time(NULL), timestamp)) return;
    const char *result = "rejected";
    if (!error) {
        ap_state_t candidate = s_state;
        error = ap_apply(&candidate, &command);
        if (!error) {
            esp_err_t hardware = ap_output_fan(candidate.power);
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
    ESP_LOGI(TAG, "Air purifier command %s: %s%s%s",
             command.id, result, error ? ": " : "", error ? error : "");
}

static void flush_acks(void)
{
    for (int i = 0; i < HISTORY_SIZE; ++i) {
        ack_record_t *record = &s_history[i];
        if (!record->pending) continue;
        cJSON *root = ap_ack_json(record->id, record->result,
                                   record->reason, &record->snapshot, record->timestamp);
        if (!ap_publish(true, root)) break;
        record->pending = false;
    }
}

void app_main(void)
{
    /* Always boot with the relay OFF and automatic control disabled. */
    ESP_ERROR_CHECK(ap_hardware_init());
    ap_init(&s_state);
    ap_requests = xQueueCreate(8, sizeof(ap_request_t));
    ap_network_events = xEventGroupCreate();
    configASSERT(ap_requests && ap_network_events);
    configASSERT(xTaskCreate(ap_network_task, "room_air_network", 6144, NULL, 5, NULL) == pdPASS);
    static ap_request_t request;
    int64_t next_report = 0;
    int64_t next_error_log = 0;
    int64_t next_sample = 0;
    bool was_online = false;
    for (;;) {
        int64_t now = esp_timer_get_time();
        if (now >= next_sample) {
            int raw = -1, mv = -1;
            esp_err_t read_error = ap_read_sensor(&raw, &mv);
            ap_quality_t previous_quality = s_state.quality;
            bool previous_valid = s_state.sensor_valid, previous_warmup = s_state.warming_up;
            bool previous_ppm_valid = s_state.ppm_valid;
            ap_sample(&s_state, read_error == ESP_OK, raw, mv, now,
                CONFIG_AP_WARMUP_SEC, CONFIG_AP_GOOD_RAW, CONFIG_AP_BAD_RAW, CONFIG_AP_VERY_BAD_RAW);
            ap_estimate_ppm(&s_state, CONFIG_AP_MQ135_SUPPLY_MV, CONFIG_AP_MQ135_DIVIDER_MILLI,
                CONFIG_AP_MQ135_RL_OHM, CONFIG_AP_MQ135_R0_OHM);
            if (previous_quality != s_state.quality || previous_valid != s_state.sensor_valid ||
                previous_warmup != s_state.warming_up || previous_ppm_valid != s_state.ppm_valid) s_dirty = true;
            if (read_error != ESP_OK && now >= next_error_log) {
                ESP_LOGW(TAG, "MQ135 sample failed: %s", esp_err_to_name(read_error));
                next_error_log = now + 5000000;
            }
            ap_state_t candidate = s_state;
            if (ap_automatic(&candidate)) {
                esp_err_t error = ap_output_fan(candidate.power);
                if (error == ESP_OK) {
                    s_state = candidate;
                    s_dirty = true;
                    ESP_LOGI(TAG, "Automatic fan %s (raw=%d)", s_state.power ? "on" : "off", raw);
                } else if (now >= next_error_log) {
                    ESP_LOGE(TAG, "Relay output failed: %s", esp_err_to_name(error));
                    next_error_log = now + 5000000;
                }
            }
            static const char *levels[] = {"unknown", "good", "normal", "bad", "very_bad"};
            char raw_text[12], mv_text[12], ppm_text[32];
            if (s_state.ppm_valid) snprintf(ppm_text, sizeof(ppm_text), "%.3f", s_state.ppm);
            else snprintf(ppm_text, sizeof(ppm_text), "N/A");
            if (raw >= 0) snprintf(raw_text, sizeof(raw_text), "%d", raw);
            else snprintf(raw_text, sizeof(raw_text), "N/A");
            if (mv >= 0) snprintf(mv_text, sizeof(mv_text), "%d", mv);
            else snprintf(mv_text, sizeof(mv_text), "N/A");
            unsigned warmup_left = s_state.warming_up ?
                (unsigned)(((int64_t)CONFIG_AP_WARMUP_SEC * 1000000 - now + 999999) / 1000000) : 0;
            ESP_LOGI(TAG, "MQ135 raw=%s adcMv=%s level=%s status=%s warmupLeft=%us mode=%s fan=%s ppm=%s (estimated)",
                raw_text, mv_text, levels[s_state.quality],
                !s_state.sensor_valid ? "sensor_error" : s_state.warming_up ? "warming_up" : "ready",
                warmup_left, s_state.mode == AP_AUTO ? "auto" : "manual", s_state.power ? "on" : "off", ppm_text);
            next_sample = now + 1000000;
        }
        if (xQueueReceive(ap_requests, &request, 0) == pdTRUE)
            process_request(&request);
        bool online = (xEventGroupGetBits(ap_network_events) & AP_NETWORK_ONLINE) != 0;
        if (online) {
            if (!was_online) s_dirty = true;
            flush_acks();
            char timestamp[32];
            if (ap_timestamp(time(NULL), timestamp)) {
                if ((s_dirty || now >= next_report) &&
                    ap_publish(false, ap_state_json(&s_state, timestamp))) {
                    s_dirty = false;
                    next_report = now + REPORT_INTERVAL_US;
                }
            }
        }
        was_online = online;
        vTaskDelay(pdMS_TO_TICKS(20));
    }
}
