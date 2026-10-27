#include "water_model.h"

#include <math.h>
#include <stdio.h>
#include <string.h>

static bool nonempty_string(const cJSON *value, size_t max_length)
{
    return cJSON_IsString(value) && value->valuestring[0] &&
           strlen(value->valuestring) <= max_length;
}

const char *water_parse_command(const char *json, size_t length,
                                const char *device_id, water_command_t *command)
{
    memset(command, 0, sizeof(*command));
    if (!json || length == 0 || length > WATER_MAX_COMMAND_SIZE || memchr(json, '\0', length)) {
        return "invalid_payload_size";
    }
    cJSON *root = cJSON_ParseWithLengthOpts(json, length + 1, NULL, true);
    if (!cJSON_IsObject(root)) {
        cJSON_Delete(root);
        return "invalid_json";
    }
    const char *error = NULL;
    const cJSON *id = cJSON_GetObjectItemCaseSensitive(root, "commandId");
    const cJSON *device = cJSON_GetObjectItemCaseSensitive(root, "deviceId");
    const cJSON *issued = cJSON_GetObjectItemCaseSensitive(root, "issuedAt");
    const cJSON *type = cJSON_GetObjectItemCaseSensitive(root, "type");
    const cJSON *amount = cJSON_GetObjectItemCaseSensitive(root, "amountMl");
    if (!nonempty_string(id, sizeof(command->command_id) - 1)) {
        error = "invalid_command_id";
        goto done;
    }
    snprintf(command->command_id, sizeof(command->command_id), "%s", id->valuestring);
    if (!cJSON_IsString(device) || strcmp(device->valuestring, device_id) != 0) {
        error = "device_id_mismatch";
    } else if (!nonempty_string(issued, 64)) {
        error = "missing_issued_at";
    } else if (!cJSON_IsString(type) || strcmp(type->valuestring, "dispense") != 0) {
        error = "invalid_type";
    } else if (!cJSON_IsNumber(amount) || !isfinite(amount->valuedouble) ||
               amount->valuedouble < 1 || amount->valuedouble > WATER_MAX_AMOUNT_ML ||
               floor(amount->valuedouble) != amount->valuedouble) {
        error = "invalid_amount_ml";
    } else {
        command->action = WATER_DISPENSE;
        command->amount_ml = (int)amount->valuedouble;
    }
done:
    cJSON_Delete(root);
    return error;
}

static int dispensed_ml(const water_state_t *state, int64_t now_us)
{
    const int64_t elapsed = now_us > state->started_us ? now_us - state->started_us : 0;
    /* Clamp elapsed before multiplying so long offline periods cannot overflow. */
    const int64_t duration = ((int64_t)state->target_ml * 1000000 + state->flow_ml_sec - 1) /
                             state->flow_ml_sec;
    return elapsed >= duration ? state->target_ml :
           (int)(elapsed * state->flow_ml_sec / 1000000);
}

bool water_tick(water_state_t *state, int64_t now_us)
{
    if (!state->dispensing || dispensed_ml(state, now_us) < state->target_ml) {
        return false;
    }
    state->dispensing = false;
    state->has_last_amount = true;
    state->last_dispensed_ml = state->target_ml;
    return true;
}

const char *water_apply(water_state_t *state, const water_command_t *command,
                        int64_t now_us, int flow_ml_sec)
{
    if (command->action == WATER_DISPENSE) {
        if (state->dispensing) {
            return "busy";
        }
        if (command->amount_ml < 1 || command->amount_ml > WATER_MAX_AMOUNT_ML || flow_ml_sec < 1) {
            return "invalid_amount_ml";
        }
        state->dispensing = true;
        state->has_last_amount = false;
        state->target_ml = command->amount_ml;
        state->flow_ml_sec = flow_ml_sec;
        state->started_us = now_us;
    } else if (command->action == WATER_STOP && command->local) {
        if (state->dispensing) {
            state->last_dispensed_ml = dispensed_ml(state, now_us);
            state->has_last_amount = true;
            state->dispensing = false;
        }
    } else {
        return "invalid_type";
    }
    snprintf(state->command_id, sizeof(state->command_id), "%s", command->command_id);
    state->local_control = command->local;
    return NULL;
}

bool water_timestamp(time_t now, char output[32])
{
    if (now < 1704067200) {
        return false;
    }
    const time_t korea_time = now + 9 * 60 * 60;
    struct tm parts;
    return gmtime_r(&korea_time, &parts) != NULL &&
           strftime(output, 32, "%Y-%m-%dT%H:%M:%S+09:00", &parts) != 0;
}

cJSON *water_state_json(const water_state_t *state, const char *timestamp)
{
    cJSON *root = cJSON_CreateObject();
    if (!root) {
        return NULL;
    }
    if (!cJSON_AddStringToObject(root, "reportedAt", timestamp) ||
        !cJSON_AddStringToObject(root, "status", state->dispensing ? "dispensing" : "idle")) {
        goto fail;
    }
    if (state->dispensing || !state->has_last_amount) {
        if (!cJSON_AddNullToObject(root, "lastDispensedMl")) {
            goto fail;
        }
    } else if (!cJSON_AddNumberToObject(root, "lastDispensedMl", state->last_dispensed_ml)) {
        goto fail;
    }
    if (state->command_id[0]) {
        cJSON *control = cJSON_AddObjectToObject(root, "lastControl");
        if (!control ||
            !cJSON_AddStringToObject(control, "publisher", state->local_control ? "console" : "api") ||
            !cJSON_AddStringToObject(control, "commandId", state->command_id)) {
            goto fail;
        }
    }
    return root;
fail:
    cJSON_Delete(root);
    return NULL;
}
