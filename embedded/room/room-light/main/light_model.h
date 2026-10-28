#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <time.h>
#include "cJSON.h"

#define RL_COMMAND_ID_SIZE 128
#define RL_MAX_PAYLOAD 1024
#define RL_DEVICE_ID "light-01"
#define RL_TOPIC_BASE "home/room/light/" RL_DEVICE_ID

typedef enum { RL_ON, RL_OFF, RL_BLINK, RL_FADEOUT } rl_action_t;
typedef enum { RL_STEADY, RL_BLINKING, RL_FADING } rl_mode_t;

typedef struct {
    char id[RL_COMMAND_ID_SIZE];
    rl_action_t action;
    int brightness;
    int duration_sec;
} rl_command_t;

typedef struct {
    bool power;
    int brightness;
    rl_mode_t mode;
    int64_t start_us;
    int64_t end_us;
    int start_brightness;
    int target_brightness;
} rl_light_view_t;

typedef struct {
    rl_light_view_t light;
    rl_light_view_t restore;
    char light_command_id[RL_COMMAND_ID_SIZE];
} rl_state_t;

/* Decode a bounded, not necessarily NUL-terminated payload. NULL means valid.
 * Preserve a valid commandId even when rejecting the rest of the command. */
const char *rl_parse(const char *json, size_t size, rl_command_t *out);
/* Apply to a candidate snapshot; the caller commits it only after hardware success. */
const char *rl_apply(rl_state_t *state, const rl_command_t *command, int64_t now_us);
bool rl_tick(rl_state_t *state, int64_t now_us);
bool rl_timestamp(time_t now, char out[32]);
cJSON *rl_state_json(const rl_state_t *state, const char *timestamp);
cJSON *rl_ack_json(const char *command_id, const char *result,
                    const char *reason, const rl_state_t *state, const char *timestamp);
