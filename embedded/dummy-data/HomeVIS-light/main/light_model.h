#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <time.h>
#include "cJSON.h"

#define LIGHT_COMMAND_ID_SIZE 128
#define LIGHT_MAX_COMMAND_SIZE 1024
#define LIGHT_BLINK_HALF_PERIOD_US INT64_C(500000)

typedef enum { LIGHT_ON, LIGHT_OFF, LIGHT_BLINK } light_action_t;

typedef struct {
    char command_id[LIGHT_COMMAND_ID_SIZE];
    light_action_t action;
    int duration_sec;
    bool local;
} light_command_t;

typedef struct {
    bool power;
    bool blinking;
    bool restore_power;
    int64_t blink_start_us;
    int64_t blink_end_us;
    char command_id[LIGHT_COMMAND_ID_SIZE];
    bool local_control;
} light_state_t;

/* NULL means valid. A usable command_id is preserved for rejected-command ACKs. */
const char *light_parse_command(const char *json, size_t length,
                                const char *device_id, light_command_t *command);
void light_apply(light_state_t *state, const light_command_t *command, int64_t now_us);
bool light_tick(light_state_t *state, int64_t now_us);
bool light_timestamp(time_t now, char output[32]);
cJSON *light_state_json(const light_state_t *state, const char *timestamp);
