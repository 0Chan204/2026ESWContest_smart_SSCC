#include "induction_payload.h"

#include <math.h>
#include <stdio.h>
#include <string.h>
#include <strings.h>

#define AMBIENT_C 25.0
#define RESET_C 60.0
#define COOLING_C_SEC 2.0

static bool nonempty_string(const cJSON *value, size_t limit)
{
    return cJSON_IsString(value) && value->valuestring[0] && strlen(value->valuestring) <= limit;
}

const char *induction_parse_command(const char *json, size_t length, induction_command_t *command)
{
    memset(command, 0, sizeof(*command));
    if (!json || !length || length > INDUCTION_MAX_COMMAND_SIZE || memchr(json, '\0', length)) {
        return "invalid_payload_size";
    }
    cJSON *root = cJSON_ParseWithLengthOpts(json, length + 1, NULL, true);
    if (!cJSON_IsObject(root)) {
        cJSON_Delete(root);
        return "invalid_json";
    }
    const char *error = NULL;
    const cJSON *id = cJSON_GetObjectItemCaseSensitive(root, "commandId");
    const cJSON *issued = cJSON_GetObjectItemCaseSensitive(root, "issuedAt");
    const cJSON *burner = cJSON_GetObjectItemCaseSensitive(root, "burnerId");
    const cJSON *type = cJSON_GetObjectItemCaseSensitive(root, "type");
    const cJSON *level = cJSON_GetObjectItemCaseSensitive(root, "level");
    if (!nonempty_string(id, sizeof(command->command_id) - 1)) {
        error = "invalid_command_id";
        goto done;
    }
    snprintf(command->command_id, sizeof(command->command_id), "%s", id->valuestring);
    if (!nonempty_string(issued, 64)) {
        error = "missing_issued_at";
    } else if (!cJSON_IsString(burner) || strcmp(burner->valuestring, INDUCTION_BURNER_ID)) {
        error = "burner_id_mismatch";
    } else if (!cJSON_IsString(type)) {
        error = "invalid_type";
    } else if (!strcmp(type->valuestring, "turn_on")) {
        command->action = INDUCTION_TURN_ON;
    } else if (!strcmp(type->valuestring, "turn_off")) {
        command->action = INDUCTION_TURN_OFF;
    } else if (!strcmp(type->valuestring, "set_level")) {
        command->action = INDUCTION_SET_LEVEL;
        if (!level) {
            error = "missing_level";
        }
    } else {
        error = "invalid_type";
    }
    if (!error && level) {
        if (command->action == INDUCTION_TURN_OFF) {
            error = "unexpected_level";
        } else if (!cJSON_IsNumber(level) || !isfinite(level->valuedouble) ||
                   level->valuedouble < 1 || level->valuedouble > 9 ||
                   floor(level->valuedouble) != level->valuedouble) {
            error = "invalid_level";
        } else {
            command->level = (int)level->valuedouble;
        }
    }
done:
    cJSON_Delete(root);
    return error;
}

void induction_init(induction_state_t *state, int64_t now_us)
{
    *state = (induction_state_t){.temperature = AMBIENT_C, .updated_us = now_us,
                                .publisher = INDUCTION_USER};
}

const char *induction_mode_name(induction_mode_t mode)
{
    switch (mode) {
    case INDUCTION_ON: return "on";
    case INDUCTION_OVERHEATED: return "overheated";
    case INDUCTION_COOLING: return "cooling";
    default: return "off";
    }
}

bool induction_console_action(const char *input, induction_action_t *action)
{
    if (!input || !action) {
        return false;
    }
    if (!strcmp(input, "1") || !strcasecmp(input, "off")) {
        *action = INDUCTION_SELECT_OFF;
    } else if (!strcmp(input, "2") || !strcasecmp(input, "on")) {
        *action = INDUCTION_SELECT_ON;
    } else if (!strcmp(input, "3")) {
        *action = INDUCTION_SELECT_OVERHEAT;
    } else {
        return false;
    }
    return true;
}

void induction_sample_temperature(induction_state_t *state, uint32_t random_value)
{
    if (state->mode != INDUCTION_ON && state->mode != INDUCTION_OVERHEATED) {
        return;
    }
    const int minimum = state->mode == INDUCTION_ON ? 1000 : 1500;
    const int maximum = state->mode == INDUCTION_ON ? 1200 : 1800;
    const int step = (int)(random_value % 61) - 30;
    const int value = (int)lround(state->temperature * 10.0) + step;
    state->temperature = fmin(maximum, fmax(minimum, value)) / 10.0;
}

bool induction_tick(induction_state_t *state, int64_t now_us)
{
    if (now_us <= state->updated_us) {
        return false;
    }
    const double elapsed = (now_us - state->updated_us) / 1000000.0;
    state->updated_us = now_us;
    const induction_mode_t before = state->mode;
    const bool alarm_before = state->alarm;
    if (state->mode == INDUCTION_ON) {
        state->active_sec = (uint64_t)((now_us - state->started_us) / 1000000);
    } else if (state->mode == INDUCTION_COOLING) {
        state->temperature = fmax(AMBIENT_C, state->temperature - COOLING_C_SEC * elapsed);
        if (state->alarm && state->temperature <= RESET_C) {
            state->alarm = false;
        }
        if (state->temperature <= AMBIENT_C) {
            state->mode = INDUCTION_OFF;
        }
    }
    /* Selected off/overheat scenarios persist until another control is applied. */
    return state->mode != before || state->alarm != alarm_before;
}

const char *induction_apply(induction_state_t *state, const induction_command_t *command,
                            int64_t now_us, int default_level)
{
    if (command->action == INDUCTION_SELECT_OFF || command->action == INDUCTION_SELECT_ON ||
        command->action == INDUCTION_SELECT_OVERHEAT) {
        if (!command->local) {
            return "invalid_type";
        }
        if (default_level < 1 || default_level > 9) {
            return "invalid_level";
        }
        if (command->action == INDUCTION_SELECT_OFF) {
            induction_init(state, now_us);
        } else if (command->action == INDUCTION_SELECT_ON) {
            if (state->mode != INDUCTION_ON) {
                state->started_us = now_us;
                state->active_sec = 0;
            }
            state->mode = INDUCTION_ON;
            state->level = default_level;
            state->temperature = 110.0;
            state->alarm = false;
            state->publisher = INDUCTION_USER;
        } else {
            state->mode = INDUCTION_OVERHEATED;
            state->temperature = 165.0;
            state->level = 0;
            state->alarm = true;
            state->publisher = INDUCTION_SYSTEM;
        }
        state->command_id[0] = '\0';
        return NULL;
    }
    if (command->action == INDUCTION_TURN_OFF) {
        state->level = 0;
        /* Server Off stops the overheat scenario and allows gradual cooling. */
        state->mode = state->temperature > AMBIENT_C ? INDUCTION_COOLING : INDUCTION_OFF;
    } else if (command->action == INDUCTION_TURN_ON || command->action == INDUCTION_SET_LEVEL) {
        const int level = command->level ? command->level : default_level;
        if (level < 1 || level > 9 ||
            (command->action == INDUCTION_SET_LEVEL && !command->level)) {
            return "invalid_level";
        }
        if (state->alarm || state->mode == INDUCTION_OVERHEATED) {
            return "overheated";
        }
        if (state->mode != INDUCTION_ON) {
            state->started_us = now_us;
            state->active_sec = 0;
            state->temperature = 110.0;
        }
        state->mode = INDUCTION_ON;
        state->level = level;
    } else {
        return "invalid_type";
    }
    state->publisher = command->local ? INDUCTION_USER : INDUCTION_API;
    snprintf(state->command_id, sizeof(state->command_id), "%s",
             command->local ? "" : command->command_id);
    return NULL;
}

bool induction_timestamp(time_t now, char output[32])
{
    if (now < 1704067200) {
        return false;
    }
    const time_t korea_time = now + 9 * 60 * 60;
    struct tm parts;
    return gmtime_r(&korea_time, &parts) &&
           strftime(output, 32, "%Y-%m-%dT%H:%M:%S+09:00", &parts) != 0;
}

cJSON *induction_burner_json(const induction_state_t *state)
{
    cJSON *root = cJSON_CreateObject();
    if (!root) {
        return NULL;
    }
    if (!cJSON_AddStringToObject(root, "burnerId", INDUCTION_BURNER_ID) ||
        !cJSON_AddStringToObject(root, "deviceState", induction_mode_name(state->mode)) ||
        !cJSON_AddNumberToObject(root, "level", state->level) ||
        !cJSON_AddNumberToObject(root, "temperature", round(state->temperature * 10.0) / 10.0) ||
        !cJSON_AddNumberToObject(root, "activeSec", (double)state->active_sec)) {
        cJSON_Delete(root);
        return NULL;
    }
    return root;
}

cJSON *induction_state_json(const induction_state_t *state, const char *timestamp)
{
    cJSON *root = cJSON_CreateObject();
    if (!root) {
        return NULL;
    }
    cJSON *burners = cJSON_AddArrayToObject(root, "burners");
    cJSON *burner = induction_burner_json(state);
    if (!burners || !burner || !cJSON_AddItemToArray(burners, burner)) {
        cJSON_Delete(burner);
        goto fail;
    }
    cJSON *control = cJSON_AddObjectToObject(root, "lastControl");
    const char *publisher = state->publisher == INDUCTION_API ? "api" :
                            state->publisher == INDUCTION_SYSTEM ? "system" : "user";
    if (!control || !cJSON_AddStringToObject(control, "publisher", publisher) ||
        (state->publisher == INDUCTION_API &&
         !cJSON_AddStringToObject(control, "commandId", state->command_id)) ||
        !cJSON_AddStringToObject(root, "reportedAt", timestamp) ||
        !cJSON_AddStringToObject(root, "alarm", state->alarm ? "on" : "off")) {
        goto fail;
    }
    return root;
fail:
    cJSON_Delete(root);
    return NULL;
}

cJSON *induction_ack_json(const char *command_id, const char *result, const char *reason,
                          const induction_state_t *state, const char *timestamp)
{
    cJSON *root = cJSON_CreateObject();
    if (!root) {
        return NULL;
    }
    if (!cJSON_AddStringToObject(root, "commandId", command_id) ||
        !cJSON_AddStringToObject(root, "result", result) ||
        !cJSON_AddStringToObject(root, "appliedAt", timestamp) ||
        (reason && !cJSON_AddStringToObject(root, "reason", reason))) {
        goto fail;
    }
    if (state) {
        cJSON *burner = induction_burner_json(state);
        if (!burner || !cJSON_AddItemToObject(root, "burnerState", burner)) {
            cJSON_Delete(burner);
            goto fail;
        }
    }
    return root;
fail:
    cJSON_Delete(root);
    return NULL;
}
