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

const char *klh_parse(klh_device_t device, const char *json, size_t size, klh_command_t *out)
{
    memset(out, 0, sizeof(*out));
    out->device = device;
    if (!json || !size || size > KLH_MAX_PAYLOAD || memchr(json, '\0', size))
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
    if (!text(id, KLH_COMMAND_ID_SIZE - 1)) {
        error = "invalid_command_id";
        goto done;
    }
    snprintf(out->id, sizeof(out->id), "%s", id->valuestring);
    while (end < json + size && (*end == ' ' || *end == '\r' || *end == '\n' || *end == '\t'))
        ++end;
    if (end != json + size) {
        error = "invalid_json";
    } else if (!text(target, 64) || strcmp(target->valuestring, device == KLH_LIGHT ? KLH_LIGHT_ID : KLH_FAN_ID)) {
        error = "device_id_mismatch";
    } else if (!text(issued, 64)) {
        error = "missing_issued_at";
    } else if (!text(type, 32)) {
        error = "invalid_type";
    } else if (strcmp(type->valuestring, "on") == 0) {
        out->action = KLH_ON;
        out->brightness = 100;
        if (device == KLH_LIGHT && brightness && !integer(brightness, 100, 100))
            error = "on_requires_brightness_100";
    } else if (strcmp(type->valuestring, "off") == 0) {
        out->action = KLH_OFF;
    } else if (device == KLH_FAN && strcmp(type->valuestring, "set_speed") == 0) {
        error = "unsupported_speed_control";
    } else if (device == KLH_LIGHT && strcmp(type->valuestring, "blink") == 0) {
        out->action = KLH_BLINK;
        if (!integer(duration, 1, 3600)) error = "invalid_duration_sec";
        else out->duration_sec = duration->valueint;
    } else if (device == KLH_LIGHT && strcmp(type->valuestring, "fadeout") == 0) {
        out->action = KLH_FADEOUT;
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

static void advance_fade(klh_light_view_t *light, int64_t now_us)
{
    if (now_us >= light->end_us) {
        light->brightness = light->target_brightness;
        light->power = light->target_brightness > 0;
        light->mode = KLH_STEADY;
    } else if (now_us > light->start_us) {
        int64_t elapsed = now_us - light->start_us;
        int64_t duration = light->end_us - light->start_us;
        light->brightness = light->start_brightness +
            (int)((light->target_brightness - light->start_brightness) * elapsed / duration);
    }
}

bool klh_tick(klh_state_t *state, int64_t now_us)
{
    klh_light_view_t *light = &state->light;
    bool power = light->power;
    int brightness = light->brightness;
    klh_mode_t mode = light->mode;
    if (light->mode == KLH_FADING) {
        advance_fade(light, now_us);
    } else if (light->mode == KLH_BLINKING) {
        if (now_us >= light->end_us) {
            *light = state->restore;
            if (light->mode == KLH_FADING) advance_fade(light, now_us);
        } else {
            light->power = ((now_us - light->start_us) / 500000) % 2 == 0;
            light->brightness = light->power ? 100 : 0;
        }
    }
    return power != light->power || brightness != light->brightness || mode != light->mode;
}

const char *klh_apply(klh_state_t *state, const klh_command_t *command, int64_t now_us)
{
    if (command->device == KLH_FAN) {
        if (command->action != KLH_ON && command->action != KLH_OFF) return "invalid_type";
        state->fan_power = command->action == KLH_ON;
        snprintf(state->fan_command_id, sizeof(state->fan_command_id), "%s", command->id);
        return NULL;
    }
    klh_tick(state, now_us);
    klh_light_view_t *light = &state->light;
    switch (command->action) {
    case KLH_ON:
    case KLH_OFF:
        *light = (klh_light_view_t) {
            .power = command->action == KLH_ON,
            .brightness = command->action == KLH_ON ? 100 : 0,
            .mode = KLH_STEADY,
        };
        break;
    case KLH_BLINK:
        if (light->mode != KLH_BLINKING) state->restore = *light;
        *light = (klh_light_view_t) {
            .power = true, .brightness = 100, .mode = KLH_BLINKING,
            .start_us = now_us, .end_us = now_us + (int64_t)command->duration_sec * 1000000,
        };
        break;
    case KLH_FADEOUT:
        /* A new explicit command interrupts blink and cancels its restoration. */
        if (!light->power) return "light_is_off";
        if (command->brightness > light->brightness) return "fadeout_cannot_increase_brightness";
        *light = (klh_light_view_t) {
            .power = true, .brightness = light->brightness, .mode = KLH_FADING,
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

bool klh_timestamp(time_t now, char out[32])
{
    struct tm parts;
    return now >= 1704067200 && gmtime_r(&now, &parts) &&
           strftime(out, 32, "%Y-%m-%dT%H:%M:%SZ", &parts) != 0;
}

cJSON *klh_state_json(klh_device_t device, const klh_state_t *state, const char *timestamp)
{
    cJSON *root = cJSON_CreateObject();
    if (!root) return NULL;
    const char *id = device == KLH_LIGHT ? state->light_command_id : state->fan_command_id;
    bool power = device == KLH_LIGHT ? state->light.power : state->fan_power;
    if (!cJSON_AddStringToObject(root, "reportedAt", timestamp) ||
        !cJSON_AddStringToObject(root, "power", power ? "on" : "off")) goto fail;
    if (device == KLH_LIGHT) {
        const char *mode = state->light.mode == KLH_BLINKING ? "blink" :
                           state->light.mode == KLH_FADING ? "fadeout" : "steady";
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

cJSON *klh_ack_json(klh_device_t device, const char *command_id, const char *result,
                    const char *reason, const klh_state_t *state, const char *timestamp)
{
    cJSON *root = cJSON_CreateObject();
    if (!root) return NULL;
    if (!cJSON_AddStringToObject(root, "commandId", command_id) ||
        !cJSON_AddStringToObject(root, "result", result) ||
        !cJSON_AddStringToObject(root, "appliedAt", timestamp) ||
        (reason && !cJSON_AddStringToObject(root, "reason", reason))) goto fail;
    cJSON *snapshot = klh_state_json(device, state, timestamp);
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
