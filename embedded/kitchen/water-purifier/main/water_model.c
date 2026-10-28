#include "water_model.h"
#include <stdio.h>
#include <string.h>
#include <math.h>

void wp_init(wp_state_t *state)
{
    *state = (wp_state_t){.publisher = "user", .selected_ml = 120, .water_type = WP_PURIFIED};
}

bool wp_select(wp_state_t *state, unsigned key)
{
    if (state->dispensing) return false;
    if (key == 1) state->water_type = (state->water_type + 1) % 3;
    else if (key == 2 && state->selected_ml > 120) state->selected_ml -= 120;
    else if (key == 3 && state->selected_ml < 480) state->selected_ml += 120;
    else return false;
    state->publisher = "user";
    state->command_id[0] = '\0';
    return true;
}

int wp_estimated_ml(const wp_state_t *state, int64_t now)
{
    if (!state->dispensing) return state->last_ml;
    int64_t elapsed = now > state->started_us ? now - state->started_us : 0;
    if (now >= state->deadline_us) return state->target_ml;
    int64_t volume = elapsed * state->flow_ml_per_min / 60000000;
    return volume > state->target_ml ? state->target_ml : (int)volume;
}

bool wp_tick(wp_state_t *state, int64_t now)
{
    if (!state->dispensing || now < state->deadline_us) return false;
    state->last_ml = state->target_ml;
    state->dispensing = false;
    return true;
}

const char *wp_apply(wp_state_t *state, const wp_command_t *command, bool local,
                     int64_t now, int flow_ml_per_min, unsigned max_run_sec)
{
    if (command->action == WP_STOP) {
        if (state->dispensing) state->last_ml = wp_estimated_ml(state, now);
        state->dispensing = false;
    } else if (command->action == WP_DISPENSE) {
        if (state->dispensing) return "busy";
        if (command->amount_ml < 1 || command->amount_ml > 2000) return "invalid_amount_ml";
        if (flow_ml_per_min < 1 || flow_ml_per_min > 60000 || max_run_sec < 1 || max_run_sec > 300)
            return "invalid_flow_configuration";
        int64_t duration = ((int64_t)command->amount_ml * 60000000 + flow_ml_per_min - 1) / flow_ml_per_min;
        if (duration > (int64_t)max_run_sec * 1000000) return "duration_limit_exceeded";
        state->dispensing = true;
        state->target_ml = command->amount_ml;
        state->flow_ml_per_min = flow_ml_per_min;
        state->started_us = now;
        state->deadline_us = now + duration;
    } else return "invalid_type";
    state->publisher = local ? "user" : "api";
    snprintf(state->command_id, sizeof(state->command_id), "%s", local ? "" : command->id);
    return NULL;
}

static bool text(const cJSON *item, size_t max)
{
    return cJSON_IsString(item) && item->valuestring[0] && strlen(item->valuestring) <= max;
}

static bool bounded_nesting(const char *json, size_t size)
{
    int depth = 0;
    bool quoted = false, escaped = false;
    for (size_t i = 0; i < size; ++i) {
        char ch = json[i];
        if (quoted) {
            if (escaped) escaped = false;
            else if (ch == '\\') escaped = true;
            else if (ch == '"') quoted = false;
        } else if (ch == '"') {
            quoted = true;
        } else if (ch == '{' || ch == '[') {
            if (++depth > 16) return false;
        } else if (ch == '}' || ch == ']') {
            if (--depth < 0) return false;
        }
    }
    return !quoted && depth == 0;
}

const char *wp_parse(const char *json, size_t size, wp_command_t *out)
{
    memset(out, 0, sizeof(*out));
    if (!json || !size || size > WP_MAX_PAYLOAD || memchr(json, '\0', size))
        return "invalid_payload_size";
    if (!bounded_nesting(json, size)) return "invalid_json";
    const char *end = NULL;
    cJSON *root = cJSON_ParseWithLengthOpts(json, size, &end, false);
    if (!cJSON_IsObject(root)) {
        cJSON_Delete(root);
        return "invalid_json";
    }
    const char *error = NULL;
    const cJSON *id = cJSON_GetObjectItemCaseSensitive(root, "commandId");
    const cJSON *target = cJSON_GetObjectItemCaseSensitive(root, "deviceId");
    const cJSON *issued = cJSON_GetObjectItemCaseSensitive(root, "issuedAt");
    const cJSON *type = cJSON_GetObjectItemCaseSensitive(root, "type");
    if (!text(id, WP_COMMAND_ID_SIZE - 1)) {
        error = "invalid_command_id";
        goto done;
    }
    snprintf(out->id, sizeof(out->id), "%s", id->valuestring);
    while (end < json + size && (*end == ' ' || *end == '\r' || *end == '\n' || *end == '\t'))
        ++end;
    if (end != json + size) {
        error = "invalid_json";
    } else if (!text(target, 64) || strcmp(target->valuestring, WP_DEVICE_ID)) {
        error = "device_id_mismatch";
    } else if (!text(issued, 64)) {
        error = "missing_issued_at";
    } else if (!text(type, 32)) {
        error = "invalid_type";
    } else if (!strcmp(type->valuestring, "dispense")) {
        out->action = WP_DISPENSE;
        /* Server requests always dispense 120 mL, irrespective of amountMl. */
        out->amount_ml = 120;
    } else if (!strcmp(type->valuestring, "stop")) {
        out->action = WP_STOP;
    } else {
        error = "invalid_type";
    }
done:
    cJSON_Delete(root);
    return error;
}

bool wp_timestamp(time_t now, char out[32])
{
    struct tm parts;
    return now >= 1704067200 && gmtime_r(&now, &parts) &&
           strftime(out, 32, "%Y-%m-%dT%H:%M:%SZ", &parts) != 0;
}


cJSON *wp_state_json(const wp_state_t *state, const char *timestamp)
{
    cJSON *root = cJSON_CreateObject();
    if (!root) return NULL;
    if (!cJSON_AddStringToObject(root, "reportedAt", timestamp) ||
        !cJSON_AddStringToObject(root, "status", state->dispensing ? "dispensing" : "idle") ||
        !cJSON_AddNumberToObject(root, "lastDispensedMl", state->last_ml) ||
        !cJSON_AddNumberToObject(root, "targetMl", state->target_ml) ||
        !cJSON_AddBoolToObject(root, "volumeEstimated", true) ||
        !cJSON_AddBoolToObject(root, "simulated", true) ||
        !cJSON_AddNumberToObject(root, "selectedMl", state->selected_ml) ||
        !cJSON_AddStringToObject(root, "selectedWaterType", state->water_type == WP_HOT ? "hot" :
            state->water_type == WP_COLD ? "cold" : "purified") ||
        !cJSON_AddBoolToObject(root, "temperatureControlAvailable", false)) goto fail;
    cJSON *control = cJSON_AddObjectToObject(root, "lastControl");
    if (!control || !cJSON_AddStringToObject(control, "publisher", state->publisher)) goto fail;
    if (state->command_id[0] && !cJSON_AddStringToObject(control, "commandId", state->command_id)) goto fail;
    return root;
fail:
    cJSON_Delete(root);
    return NULL;
}
cJSON *wp_ack_json(const char *command_id, const char *result,
                    const char *reason, const wp_state_t *state, const char *timestamp)
{
    cJSON *root = cJSON_CreateObject();
    if (!root) return NULL;
    if (!cJSON_AddStringToObject(root, "commandId", command_id) ||
        !cJSON_AddStringToObject(root, "result", result) ||
        !cJSON_AddStringToObject(root, "appliedAt", timestamp) ||
        (reason && !cJSON_AddStringToObject(root, "reason", reason))) goto fail;
    cJSON *snapshot = wp_state_json(state, timestamp);
    if (!snapshot) goto fail;
    if (!cJSON_AddItemToObject(root, "state", snapshot)) {
        cJSON_Delete(snapshot);
        goto fail;
    }
    return root;
fail:
    cJSON_Delete(root);
    return NULL;
}
