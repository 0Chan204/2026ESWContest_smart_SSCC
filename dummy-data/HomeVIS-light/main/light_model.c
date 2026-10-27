#include "light_model.h"

#include <math.h>
#include <stdio.h>
#include <string.h>

static bool nonempty_string(const cJSON *value, size_t max_length)
{
    return cJSON_IsString(value) && value->valuestring[0] != '\0' &&
           strlen(value->valuestring) <= max_length;
}

const char *light_parse_command(const char *json, size_t length,
                                const char *device_id, light_command_t *command)
{
    memset(command, 0, sizeof(*command));
    if (length == 0 || length > LIGHT_MAX_COMMAND_SIZE || memchr(json, '\0', length)) {
        return "invalid_payload_size";
    }
    /* The transport supplies an extra NUL byte; require complete JSON consumption. */
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
    if (!nonempty_string(id, sizeof(command->command_id) - 1)) {
        error = "invalid_command_id";
        goto done;
    }
    snprintf(command->command_id, sizeof(command->command_id), "%s", id->valuestring);
    if (!cJSON_IsString(device) || strcmp(device->valuestring, device_id) != 0) {
        error = "device_id_mismatch";
    } else if (!nonempty_string(issued, 64)) {
        error = "missing_issued_at";
    } else if (!cJSON_IsString(type)) {
        error = "invalid_type";
    } else if (strcmp(type->valuestring, "on") == 0) {
        command->action = LIGHT_ON;
    } else if (strcmp(type->valuestring, "off") == 0) {
        command->action = LIGHT_OFF;
    } else if (strcmp(type->valuestring, "blink") == 0) {
        const cJSON *duration = cJSON_GetObjectItemCaseSensitive(root, "durationSec");
        if (!cJSON_IsNumber(duration) || !isfinite(duration->valuedouble) ||
            duration->valuedouble < 1 || duration->valuedouble > 86400 ||
            floor(duration->valuedouble) != duration->valuedouble) {
            error = "invalid_duration_sec";
        } else {
            command->action = LIGHT_BLINK;
            command->duration_sec = (int)duration->valuedouble;
        }
    } else {
        error = "invalid_type";
    }
done:
    cJSON_Delete(root);
    return error;
}

void light_apply(light_state_t *state, const light_command_t *command, int64_t now_us)
{
    /* Expire a previous blink before deciding the next command's restore state. */
    light_tick(state, now_us);
    if (command->action == LIGHT_BLINK) {
        if (!state->blinking) {
            state->restore_power = state->power;
        }
        state->blinking = true;
        state->power = true;
        state->blink_start_us = now_us;
        state->blink_end_us = now_us + (int64_t)command->duration_sec * 1000000;
    } else {
        state->blinking = false;
        state->power = command->action == LIGHT_ON;
    }
    snprintf(state->command_id, sizeof(state->command_id), "%s", command->command_id);
    state->local_control = command->local;
}

bool light_tick(light_state_t *state, int64_t now_us)
{
    if (!state->blinking) {
        return false;
    }
    const bool old_power = state->power;
    if (now_us >= state->blink_end_us) {
        state->blinking = false;
        state->power = state->restore_power;
        return true; /* mode changes even if the power happens to match. */
    }
    state->power = ((now_us - state->blink_start_us) / LIGHT_BLINK_HALF_PERIOD_US) % 2 == 0;
    return state->power != old_power;
}

bool light_timestamp(time_t now, char output[32])
{
    /* Do not publish fabricated 1970 timestamps before SNTP synchronization. */
    if (now < 1704067200) {
        return false;
    }
    const time_t korea_time = now + 9 * 60 * 60;
    struct tm parts;
    return gmtime_r(&korea_time, &parts) != NULL &&
           strftime(output, 32, "%Y-%m-%dT%H:%M:%S+09:00", &parts) != 0;
}

cJSON *light_state_json(const light_state_t *state, const char *timestamp)
{
    cJSON *root = cJSON_CreateObject();
    if (!root) {
        return NULL;
    }
    if (!cJSON_AddStringToObject(root, "reportedAt", timestamp) ||
        !cJSON_AddStringToObject(root, "power", state->power ? "on" : "off") ||
        !cJSON_AddStringToObject(root, "mode", state->blinking ? "blink" : "steady")) {
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
