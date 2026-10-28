#include "light_model.h"

#include <math.h>
#include <stdio.h>
#include <string.h>

static bool text(const cJSON *item, size_t max)
{
    return cJSON_IsString(item) && item->valuestring[0] && strlen(item->valuestring) <= max;
}

static bool integer(const cJSON *item, int low, int high)
{
    return cJSON_IsNumber(item) && isfinite(item->valuedouble) &&
           item->valuedouble >= low && item->valuedouble <= high &&
           floor(item->valuedouble) == item->valuedouble;
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

const char *rl_parse(const char *json, size_t size, rl_command_t *out)
{
    memset(out, 0, sizeof(*out));
    if (!json || !size || size > RL_MAX_PAYLOAD || memchr(json, '\0', size))
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
    const cJSON *brightness = cJSON_GetObjectItemCaseSensitive(root, "brightness");
    const cJSON *duration = cJSON_GetObjectItemCaseSensitive(root, "durationSec");
    if (!text(id, RL_COMMAND_ID_SIZE - 1)) {
        error = "invalid_command_id";
        goto done;
    }
    snprintf(out->id, sizeof(out->id), "%s", id->valuestring);
    while (end < json + size && (*end == ' ' || *end == '\r' || *end == '\n' || *end == '\t'))
        ++end;
    if (end != json + size) {
        error = "invalid_json";
    } else if (!text(target, 64) || strcmp(target->valuestring, RL_DEVICE_ID)) {
        error = "device_id_mismatch";
    } else if (!text(issued, 64)) {
        error = "missing_issued_at";
    } else if (!text(type, 32)) {
        error = "invalid_type";
    } else if (strcmp(type->valuestring, "on") == 0) {
        out->action = RL_ON;
        out->brightness = 100;
        if (brightness && !integer(brightness, 100, 100))
            error = "on_requires_brightness_100";
    } else if (strcmp(type->valuestring, "off") == 0) {
        out->action = RL_OFF;
    } else if (strcmp(type->valuestring, "blink") == 0) {
        out->action = RL_BLINK;
        if (!integer(duration, 1, 3600)) error = "invalid_duration_sec";
        else out->duration_sec = duration->valueint;
    } else if (strcmp(type->valuestring, "fadeout") == 0) {
        out->action = RL_FADEOUT;
        if (!integer(duration, 1, 3600)) error = "invalid_duration_sec";
        else if (!integer(brightness, 1, 100)) error = "invalid_brightness";
        else {
            out->duration_sec = duration->valueint;
            out->brightness = brightness->valueint;
        }
    } else {
        error = "invalid_type";
    }
done:
    cJSON_Delete(root);
    return error;
}

static void advance_fade(rl_light_view_t *light, int64_t now_us)
{
    if (now_us >= light->end_us) {
        light->brightness = light->target_brightness;
        light->power = light->target_brightness > 0;
        light->mode = RL_STEADY;
    } else if (now_us > light->start_us) {
        int64_t elapsed = now_us - light->start_us;
        int64_t duration = light->end_us - light->start_us;
        light->brightness = light->start_brightness +
            (int)((light->target_brightness - light->start_brightness) * elapsed / duration);
    }
}

bool rl_tick(rl_state_t *state, int64_t now_us)
{
    rl_light_view_t *light = &state->light;
    bool power = light->power;
    int brightness = light->brightness;
    rl_mode_t mode = light->mode;
    if (light->mode == RL_FADING) {
        advance_fade(light, now_us);
    } else if (light->mode == RL_BLINKING) {
        if (now_us >= light->end_us) {
            *light = state->restore;
            if (light->mode == RL_FADING) advance_fade(light, now_us);
        } else {
            light->power = ((now_us - light->start_us) / 500000) % 2 == 0;
            light->brightness = light->power ? 100 : 0;
        }
    }
    return power != light->power || brightness != light->brightness || mode != light->mode;
}

const char *rl_apply(rl_state_t *state, const rl_command_t *command, int64_t now_us)
{
    rl_tick(state, now_us);
    rl_light_view_t *light = &state->light;
    switch (command->action) {
    case RL_ON:
    case RL_OFF:
        *light = (rl_light_view_t) {
            .power = command->action == RL_ON,
            .brightness = command->action == RL_ON ? 100 : 0,
            .mode = RL_STEADY,
        };
        break;
    case RL_BLINK:
        if (light->mode != RL_BLINKING) state->restore = *light;
        *light = (rl_light_view_t) {
            .power = true, .brightness = 100, .mode = RL_BLINKING,
            .start_us = now_us, .end_us = now_us + (int64_t)command->duration_sec * 1000000,
        };
        break;
    case RL_FADEOUT:
        /* A new explicit command interrupts blink and cancels its restoration. */
        if (!light->power) return "light_is_off";
        if (command->brightness > light->brightness) return "fadeout_cannot_increase_brightness";
        *light = (rl_light_view_t) {
            .power = true, .brightness = light->brightness, .mode = RL_FADING,
            .start_brightness = light->brightness, .target_brightness = command->brightness,
            .start_us = now_us, .end_us = now_us + (int64_t)command->duration_sec * 1000000,
        };
        break;
    default:
        return "invalid_type";
    }
    snprintf(state->light_command_id, sizeof(state->light_command_id), "%s", command->id);
    return NULL;
}

bool rl_timestamp(time_t now, char out[32])
{
    struct tm parts;
    return now >= 1704067200 && gmtime_r(&now, &parts) &&
           strftime(out, 32, "%Y-%m-%dT%H:%M:%SZ", &parts) != 0;
}

cJSON *rl_state_json(const rl_state_t *state, const char *timestamp)
{
    cJSON *root = cJSON_CreateObject();
    if (!root) return NULL;
    const char *id = state->light_command_id;
    const char *mode = state->light.mode == RL_BLINKING ? "blink" :
                       state->light.mode == RL_FADING ? "fadeout" : "steady";
    if (!cJSON_AddStringToObject(root, "reportedAt", timestamp) ||
        !cJSON_AddStringToObject(root, "power", state->light.power ? "on" : "off") ||
        !cJSON_AddNumberToObject(root, "brightness", state->light.brightness) ||
        !cJSON_AddStringToObject(root, "mode", mode)) goto fail;
    cJSON *control = cJSON_AddObjectToObject(root, "lastControl");
    if (!control || !cJSON_AddStringToObject(control, "publisher", id[0] ? "api" : "user")) goto fail;
    if (id[0] && !cJSON_AddStringToObject(control, "commandId", id)) goto fail;
    return root;
fail:
    cJSON_Delete(root);
    return NULL;
}

cJSON *rl_ack_json(const char *command_id, const char *result,
                    const char *reason, const rl_state_t *state, const char *timestamp)
{
    cJSON *root = cJSON_CreateObject();
    if (!root) return NULL;
    if (!cJSON_AddStringToObject(root, "commandId", command_id) ||
        !cJSON_AddStringToObject(root, "result", result) ||
        !cJSON_AddStringToObject(root, "appliedAt", timestamp) ||
        (reason && !cJSON_AddStringToObject(root, "reason", reason))) goto fail;
    cJSON *snapshot = rl_state_json(state, timestamp);
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
