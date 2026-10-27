#include "device_model.h"

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

const char *tlf_parse(tlf_device_t device, const char *json, size_t size, tlf_command_t *out)
{
    memset(out, 0, sizeof(*out));
    out->device = device;
    if (!json || !size || size > TLF_MAX_PAYLOAD || memchr(json, '\0', size))
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
    if (!text(id, TLF_COMMAND_ID_SIZE - 1)) {
        error = "invalid_command_id";
        goto done;
    }
    snprintf(out->id, sizeof(out->id), "%s", id->valuestring);
    while (end < json + size && (*end == ' ' || *end == '\r' || *end == '\n' || *end == '\t'))
        ++end;
    if (end != json + size) {
        error = "invalid_json";
    } else if (!text(target, 64) || strcmp(target->valuestring, device == TLF_LIGHT ? TLF_LIGHT_ID : TLF_FAN_ID)) {
        error = "device_id_mismatch";
    } else if (!text(issued, 64)) {
        error = "missing_issued_at";
    } else if (!text(type, 32)) {
        error = "invalid_type";
    } else if (strcmp(type->valuestring, "on") == 0) {
        out->action = TLF_ON;
        out->brightness = 100;
        if (device == TLF_LIGHT && brightness && !integer(brightness, 100, 100))
            error = "on_requires_brightness_100";
    } else if (strcmp(type->valuestring, "off") == 0) {
        out->action = TLF_OFF;
    } else if (device == TLF_FAN && strcmp(type->valuestring, "set_speed") == 0) {
        error = "unsupported_speed_control";
    } else if (device == TLF_LIGHT && strcmp(type->valuestring, "blink") == 0) {
        out->action = TLF_BLINK;
        if (!integer(duration, 1, 3600)) error = "invalid_duration_sec";
        else out->duration_sec = duration->valueint;
    } else if (device == TLF_LIGHT && strcmp(type->valuestring, "fadeout") == 0) {
        out->action = TLF_FADEOUT;
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

static void advance_fade(tlf_light_view_t *light, int64_t now_us)
{
    if (now_us >= light->end_us) {
        light->brightness = light->target_brightness;
        light->power = light->target_brightness > 0;
        light->mode = TLF_STEADY;
    } else if (now_us > light->start_us) {
        int64_t elapsed = now_us - light->start_us;
        int64_t duration = light->end_us - light->start_us;
        light->brightness = light->start_brightness +
            (int)((light->target_brightness - light->start_brightness) * elapsed / duration);
    }
}

bool tlf_tick(tlf_state_t *state, int64_t now_us)
{
    tlf_light_view_t *light = &state->light;
    bool power = light->power;
    int brightness = light->brightness;
    tlf_mode_t mode = light->mode;
    if (light->mode == TLF_FADING) {
        advance_fade(light, now_us);
    } else if (light->mode == TLF_BLINKING) {
        if (now_us >= light->end_us) {
            *light = state->restore;
            if (light->mode == TLF_FADING) advance_fade(light, now_us);
        } else {
            light->power = ((now_us - light->start_us) / 500000) % 2 == 0;
            light->brightness = light->power ? 100 : 0;
        }
    }
    return power != light->power || brightness != light->brightness || mode != light->mode;
}

const char *tlf_apply(tlf_state_t *state, const tlf_command_t *command, int64_t now_us)
{
    if (command->device == TLF_FAN) {
        if (command->action != TLF_ON && command->action != TLF_OFF) return "invalid_type";
        state->fan_power = command->action == TLF_ON;
        snprintf(state->fan_command_id, sizeof(state->fan_command_id), "%s", command->id);
        return NULL;
    }
    tlf_tick(state, now_us);
    tlf_light_view_t *light = &state->light;
    switch (command->action) {
    case TLF_ON:
    case TLF_OFF:
        *light = (tlf_light_view_t) {
            .power = command->action == TLF_ON,
            .brightness = command->action == TLF_ON ? 100 : 0,
            .mode = TLF_STEADY,
        };
        break;
    case TLF_BLINK:
        if (light->mode != TLF_BLINKING) state->restore = *light;
        *light = (tlf_light_view_t) {
            .power = true, .brightness = 100, .mode = TLF_BLINKING,
            .start_us = now_us, .end_us = now_us + (int64_t)command->duration_sec * 1000000,
        };
        break;
    case TLF_FADEOUT:
        /* A new explicit command interrupts blink and cancels its restoration. */
        if (!light->power) return "light_is_off";
        if (command->brightness > light->brightness) return "fadeout_cannot_increase_brightness";
        *light = (tlf_light_view_t) {
            .power = true, .brightness = light->brightness, .mode = TLF_FADING,
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

bool tlf_timestamp(time_t now, char out[32])
{
    struct tm parts;
    return now >= 1704067200 && gmtime_r(&now, &parts) &&
           strftime(out, 32, "%Y-%m-%dT%H:%M:%SZ", &parts) != 0;
}

cJSON *tlf_state_json(tlf_device_t device, const tlf_state_t *state, const char *timestamp)
{
    cJSON *root = cJSON_CreateObject();
    if (!root) return NULL;
    const char *id = device == TLF_LIGHT ? state->light_command_id : state->fan_command_id;
    bool power = device == TLF_LIGHT ? state->light.power : state->fan_power;
    if (!cJSON_AddStringToObject(root, "reportedAt", timestamp) ||
        !cJSON_AddStringToObject(root, "power", power ? "on" : "off")) goto fail;
    if (device == TLF_LIGHT) {
        const char *mode = state->light.mode == TLF_BLINKING ? "blink" :
                           state->light.mode == TLF_FADING ? "fadeout" : "steady";
        if (!cJSON_AddNumberToObject(root, "brightness", state->light.brightness) ||
            !cJSON_AddStringToObject(root, "mode", mode)) goto fail;
    } else {
        /* Compatibility value only: a single relay cannot change physical speed. */
        if (!cJSON_AddStringToObject(root, "speed", "mid") ||
            !cJSON_AddBoolToObject(root, "speedControllable", false)) goto fail;
    }
    cJSON *control = cJSON_AddObjectToObject(root, "lastControl");
    if (!control || !cJSON_AddStringToObject(control, "publisher", id[0] ? "api" : "user")) goto fail;
    if (id[0] && !cJSON_AddStringToObject(control, "commandId", id)) goto fail;
    return root;
fail:
    cJSON_Delete(root);
    return NULL;
}

cJSON *tlf_ack_json(tlf_device_t device, const char *command_id, const char *result,
                    const char *reason, const tlf_state_t *state, const char *timestamp)
{
    cJSON *root = cJSON_CreateObject();
    if (!root) return NULL;
    if (!cJSON_AddStringToObject(root, "commandId", command_id) ||
        !cJSON_AddStringToObject(root, "result", result) ||
        !cJSON_AddStringToObject(root, "appliedAt", timestamp) ||
        (reason && !cJSON_AddStringToObject(root, "reason", reason))) goto fail;
    cJSON *snapshot = tlf_state_json(device, state, timestamp);
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
