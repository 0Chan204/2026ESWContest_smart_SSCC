#include "water_model.h"
#include "water_network.h"
#include "water_hardware.h"

#include <stdio.h>
#include <string.h>
#include "esp_log.h"
#include "sdkconfig.h"
#include "esp_timer.h"
#include "freertos/task.h"
#include "freertos/semphr.h"

#define HISTORY_SIZE 32
#define REPORT_INTERVAL_US INT64_C(5000000)

typedef struct {
    bool valid;
    bool pending;
    char id[WP_COMMAND_ID_SIZE];
    const char *result;
    const char *reason;
    char timestamp[32];
    wp_state_t snapshot;
} ack_record_t;

static const char *TAG = "water_purifier_control";
static wp_state_t s_state;
static ack_record_t s_history[HISTORY_SIZE];
static unsigned s_history_cursor;
static bool s_dirty = true;
static SemaphoreHandle_t s_display_mutex;
static wp_state_t s_display_state;
static int64_t s_local_stop_at;
static bool s_stop_held;

typedef struct { bool raw, stable; int64_t changed; } button_t;

static bool pressed(button_t *button, bool raw, int64_t now)
{
    if (button->raw != raw) { button->raw = raw; button->changed = now; }
    if (raw != button->stable && now - button->changed >= 40000) {
        button->stable = raw;
        return raw;
    }
    return false;
}

static void display_task(void *arg)
{
    esp_err_t error = wp_display_init();
    if (error != ESP_OK) {
        ESP_LOGW(TAG, "OLED unavailable (%s); LED and touch controls remain active", esp_err_to_name(error));
        vTaskDelete(NULL);
        return;
    }
    for (;;) {
        wp_state_t snapshot;
        xSemaphoreTake(s_display_mutex, portMAX_DELAY);
        snapshot = s_display_state;
        xSemaphoreGive(s_display_mutex);
        error = wp_display_update(&snapshot, esp_timer_get_time());
        if (error != ESP_OK) {
            ESP_LOGW(TAG, "OLED update failed: %s", esp_err_to_name(error));
            vTaskDelay(pdMS_TO_TICKS(5000));
        } else vTaskDelay(pdMS_TO_TICKS(250));
    }
}

static void local_command(wp_action_t action, int amount, int64_t now)
{
    wp_command_t command = {.action = action, .amount_ml = amount};
    wp_state_t candidate = s_state;
    const char *error = wp_apply(&candidate, &command, true, now,
        CONFIG_WP_FLOW_ML_PER_MIN, CONFIG_WP_MAX_RUN_SEC);
    if (error) { ESP_LOGW(TAG, "Local command rejected: %s", error); return; }
    if (wp_output(candidate.dispensing, candidate.water_type) != ESP_OK) {
        ESP_LOGE(TAG, "Local LED output failed");
        return;
    }
    s_state = candidate;
    s_dirty = true;
    ESP_LOGI(TAG, "Touch: %s, target=%d mL", action == WP_STOP ? "stop" : "dispense", amount);
}

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

static void process_request(const wp_request_t *request, int64_t now)
{
    wp_command_t command;
    const char *error = wp_parse(request->payload, request->length, &command);
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
    if (!wp_timestamp(time(NULL), timestamp)) return;
    const char *result = "rejected";
    if (!error && command.action == WP_DISPENSE &&
        (s_stop_held || request->received_us <= s_local_stop_at)) error = "cancelled_by_local_stop";
    if (!error) {
        wp_state_t candidate = s_state;
        error = wp_apply(&candidate, &command, false, now, CONFIG_WP_FLOW_ML_PER_MIN, CONFIG_WP_MAX_RUN_SEC);
        if (!error) {
            esp_err_t hardware = wp_output(candidate.dispensing, candidate.water_type);
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
    ESP_LOGI(TAG, "Water purifier command %s: %s%s%s",
             command.id, result, error ? ": " : "", error ? error : "");
}

static void flush_acks(void)
{
    for (int i = 0; i < HISTORY_SIZE; ++i) {
        ack_record_t *record = &s_history[i];
        if (!record->pending) continue;
        cJSON *root = wp_ack_json(record->id, record->result,
                                   record->reason, &record->snapshot, record->timestamp);
        if (!wp_publish(true, root)) break;
        record->pending = false;
    }
}

void app_main(void)
{
    /* All eight LEDs are OFF before creating any peripheral or network tasks. */
    ESP_ERROR_CHECK(wp_hardware_init());
    wp_init(&s_state);
    s_display_state = s_state;
    s_display_mutex = xSemaphoreCreateMutex();
    wp_requests = xQueueCreate(8, sizeof(wp_request_t));
    wp_network_events = xEventGroupCreate();
    configASSERT(s_display_mutex && wp_requests && wp_network_events);
    configASSERT(xTaskCreate(wp_network_task, "water_network", 6144, NULL, 4, NULL) == pdPASS);
    configASSERT(xTaskCreate(display_task, "water_display", 4096, NULL, 3, NULL) == pdPASS);
    button_t buttons[4] = {0};
    /* Ignore touch module startup calibration and require a fresh press after boot. */
    vTaskDelay(pdMS_TO_TICKS(1000));
    for (unsigned i = 0; i < 4; ++i) buttons[i].raw = buttons[i].stable = wp_touch_active(i);
    static wp_request_t request;
    int64_t next_report = 0;
    bool was_online = false;
    for (;;) {
        int64_t now = esp_timer_get_time();
        if (wp_tick(&s_state, now)) {
            ESP_ERROR_CHECK(wp_output(false, s_state.water_type));
            s_dirty = true;
            ESP_LOGI(TAG, "Dispensing complete: estimated %d mL", s_state.last_ml);
        }
        bool events[4];
        for (unsigned i = 0; i < 4; ++i) events[i] = pressed(&buttons[i], wp_touch_active(i), now);
        /* Key 4 takes priority over selection keys. Held keys never repeat. */
        s_stop_held = buttons[3].raw || buttons[3].stable;
        if (events[3]) {
            bool stopping = s_state.dispensing;
            if (stopping) s_local_stop_at = now;
            local_command(stopping ? WP_STOP : WP_DISPENSE, s_state.selected_ml, now);
        } else if (!s_stop_held) {
            for (unsigned i = 0; i < 3; ++i) {
                if (events[i]) {
                    if (wp_select(&s_state, i + 1)) s_dirty = true;
                    break;
                }
            }
        }
        if (xQueueReceive(wp_requests, &request, 0) == pdTRUE) process_request(&request, now);
        xSemaphoreTake(s_display_mutex, portMAX_DELAY);
        s_display_state = s_state;
        xSemaphoreGive(s_display_mutex);
        bool online = (xEventGroupGetBits(wp_network_events) & WP_NETWORK_ONLINE) != 0;
        if (online) {
            if (!was_online) s_dirty = true;
            flush_acks();
            char timestamp[32];
            if (wp_timestamp(time(NULL), timestamp) && (s_dirty || now >= next_report) &&
                wp_publish(false, wp_state_json(&s_state, timestamp))) {
                s_dirty = false;
                next_report = now + REPORT_INTERVAL_US;
            }
        }
        was_online = online;
        vTaskDelay(pdMS_TO_TICKS(5));
    }
}
