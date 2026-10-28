#include "air_model.h"
#include <math.h>
#include <stdio.h>
#include <string.h>

void ap_init(ap_state_t *state)
{
    *state = (ap_state_t) {
        .mode = AP_MANUAL, .warming_up = true, .raw = -1, .adc_mv = -1,
        .quality = AP_UNKNOWN, .publisher = "user",
    };
}

void ap_sample(ap_state_t *state, bool valid, int raw, int adc_mv,
               int64_t uptime_us, unsigned warmup_sec, int good_raw, int bad_raw, int very_bad_raw)
{
    state->sensor_valid = valid && raw > 0 && raw < 4095;
    state->ppm_valid = false;
    state->ppm = 0;
    state->raw = state->sensor_valid ? raw : -1;
    state->adc_mv = state->sensor_valid ? adc_mv : -1;
    state->warming_up = uptime_us < (int64_t)warmup_sec * 1000000;
    state->quality = !state->sensor_valid || state->warming_up ? AP_UNKNOWN :
        raw <= good_raw ? AP_GOOD : raw >= very_bad_raw ? AP_VERY_BAD :
        raw >= bad_raw ? AP_BAD : AP_NORMAL;
}

void ap_estimate_ppm(ap_state_t *state, int supply_mv, int divider_milli,
                     int rl_ohm, int r0_ohm)
{
    state->ppm_valid = false;
    state->ppm = 0;
    if (!state->sensor_valid || state->warming_up || state->adc_mv <= 0 ||
        supply_mv <= 0 || divider_milli < 1000 || rl_ohm <= 0 || r0_ohm <= 0) return;
    double output_mv = (double)state->adc_mv * divider_milli / 1000.0;
    if (output_mv >= supply_mv) return;
    double rs = rl_ohm * (supply_mv - output_mv) / output_mv;
    /* User-supplied mq135.c curve, using the actual circuit supply voltage. */
    double ppm = 116.6020682 * pow(rs / r0_ohm, -2.769034857);
    if (!isfinite(ppm) || ppm < 0) return;
    state->ppm = ppm;
    state->ppm_valid = true;
}

bool ap_automatic(ap_state_t *state)
{
    if (state->mode != AP_AUTO) return false;
    bool power = state->power;
    if (state->quality == AP_UNKNOWN || state->quality == AP_GOOD) power = false;
    else if (state->quality == AP_BAD || state->quality == AP_VERY_BAD) power = true;
    if (power == state->power) return false;
    state->power = power;
    state->publisher = "system";
    state->command_id[0] = '\0';
    return true;
}

const char *ap_apply(ap_state_t *state, const ap_command_t *command)
{
    if (command->action == AP_ON || command->action == AP_OFF) {
        state->mode = AP_MANUAL;
        state->power = command->action == AP_ON;
    } else if (command->action == AP_SET_MODE) {
        if (command->mode != AP_AUTO && command->mode != AP_MANUAL) return "invalid_mode";
        state->mode = command->mode;
        ap_automatic(state);
    } else return "invalid_type";
    /* Any immediate relay change here belongs to this explicit mode command. */
    state->publisher = "api";
    snprintf(state->command_id, sizeof(state->command_id), "%s", command->id);
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

const char *ap_parse(const char *json, size_t size, ap_command_t *out)
{
    memset(out, 0, sizeof(*out));
    if (!json || !size || size > AP_MAX_PAYLOAD || memchr(json, '\0', size))
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
    const cJSON *mode = cJSON_GetObjectItemCaseSensitive(root, "mode");
    if (!text(id, AP_COMMAND_ID_SIZE - 1)) {
        error = "invalid_command_id";
        goto done;
    }
    snprintf(out->id, sizeof(out->id), "%s", id->valuestring);
    while (end < json + size && (*end == ' ' || *end == '\r' || *end == '\n' || *end == '\t'))
        ++end;
    if (end != json + size) {
        error = "invalid_json";
    } else if (!text(target, 64) || strcmp(target->valuestring, AP_DEVICE_ID)) {
        error = "device_id_mismatch";
    } else if (!text(issued, 64)) {
        error = "missing_issued_at";
    } else if (!text(type, 32)) {
        error = "invalid_type";
    } else if (strcmp(type->valuestring, "on") == 0) {
        out->action = AP_ON;
    } else if (strcmp(type->valuestring, "off") == 0) {
        out->action = AP_OFF;
    } else if (strcmp(type->valuestring, "set_mode") == 0) {
        out->action = AP_SET_MODE;
        if (!text(mode, 16)) error = "invalid_mode";
        else if (!strcmp(mode->valuestring, "auto")) out->mode = AP_AUTO;
        else if (!strcmp(mode->valuestring, "manual")) out->mode = AP_MANUAL;
        else error = "invalid_mode";
    } else {
        error = "invalid_type";
    }
done:
    cJSON_Delete(root);
    return error;
}

bool ap_timestamp(time_t now, char out[32])
{
    struct tm parts;
    return now >= 1704067200 && gmtime_r(&now, &parts) &&
           strftime(out, 32, "%Y-%m-%dT%H:%M:%SZ", &parts) != 0;
}


cJSON *ap_state_json(const ap_state_t *state, const char *timestamp)
{
    static const char *levels[] = {NULL, "good", "normal", "bad", "very_bad"};
    cJSON *root = cJSON_CreateObject();
    if (!root) return NULL;
    if (!cJSON_AddStringToObject(root, "reportedAt", timestamp) ||
        !cJSON_AddStringToObject(root, "power", state->power ? "on" : "off") ||
        !cJSON_AddStringToObject(root, "mode", state->mode == AP_AUTO ? "auto" : "manual")) goto fail;
    cJSON *quality = cJSON_AddObjectToObject(root, "airQuality");
    if (!quality || !cJSON_AddStringToObject(quality, "sensor", "mq135") ||
        !cJSON_AddBoolToObject(quality, "ppmValid", state->ppm_valid) ||
        !cJSON_AddBoolToObject(quality, "ppmEstimated", true) ||
        !cJSON_AddStringToObject(quality, "ppmType", "co2_equivalent") ||
        !cJSON_AddBoolToObject(quality, "valid", state->sensor_valid && !state->warming_up) ||
        !cJSON_AddStringToObject(quality, "status", !state->sensor_valid ? "sensor_error" :
            state->warming_up ? "warming_up" : "ready") ||
        !cJSON_AddStringToObject(quality, "levelBasis", "adc_raw")) goto fail;
    if (state->ppm_valid) {
        if (!cJSON_AddNumberToObject(quality, "ppm", state->ppm)) goto fail;
    } else if (!cJSON_AddNullToObject(quality, "ppm")) goto fail;
    /* Backend accepts four grades or null, never the string "unknown". */
    if (state->quality == AP_UNKNOWN) {
        if (!cJSON_AddNullToObject(quality, "level")) goto fail;
    } else if (!cJSON_AddStringToObject(quality, "level", levels[state->quality])) goto fail;
    if (state->sensor_valid) {
        if (!cJSON_AddNumberToObject(quality, "raw", state->raw)) goto fail;
    } else if (!cJSON_AddNullToObject(quality, "raw")) goto fail;
    if (state->adc_mv >= 0) {
        if (!cJSON_AddNumberToObject(quality, "adcMv", state->adc_mv)) goto fail;
    } else if (!cJSON_AddNullToObject(quality, "adcMv")) goto fail;
    cJSON *control = cJSON_AddObjectToObject(root, "lastControl");
    if (!control || !cJSON_AddStringToObject(control, "publisher", state->publisher)) goto fail;
    if (state->command_id[0] && !cJSON_AddStringToObject(control, "commandId", state->command_id)) goto fail;
    return root;
fail:
    cJSON_Delete(root);
    return NULL;
}
cJSON *ap_ack_json(const char *command_id, const char *result,
                    const char *reason, const ap_state_t *state, const char *timestamp)
{
    cJSON *root = cJSON_CreateObject();
    if (!root) return NULL;
    if (!cJSON_AddStringToObject(root, "commandId", command_id) ||
        !cJSON_AddStringToObject(root, "result", result) ||
        !cJSON_AddStringToObject(root, "appliedAt", timestamp) ||
        (reason && !cJSON_AddStringToObject(root, "reason", reason))) goto fail;
    cJSON *snapshot = ap_state_json(state, timestamp);
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
