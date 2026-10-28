#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <time.h>
#include "cJSON.h"

#define KLH_COMMAND_ID_SIZE 128
#define KLH_MAX_PAYLOAD 1024
#define KLH_LIGHT_ID "light-02"
#define KLH_FAN_ID "fan-01"
#define KLH_LIGHT_BASE "home/kitchen/light/" KLH_LIGHT_ID
#define KLH_FAN_BASE "home/kitchen/fan/" KLH_FAN_ID

typedef enum { KLH_LIGHT, KLH_FAN } klh_device_t;
typedef enum { KLH_ON, KLH_OFF, KLH_BLINK, KLH_FADEOUT } klh_action_t;
typedef enum { KLH_STEADY, KLH_BLINKING, KLH_FADING } klh_mode_t;

typedef struct {
    klh_device_t device;
    char id[KLH_COMMAND_ID_SIZE];
    klh_action_t action;
    int brightness;
    int duration_sec;
} klh_command_t;

typedef struct {
    bool power;
    int brightness;
    klh_mode_t mode;
    int64_t start_us;
    int64_t end_us;
    int start_brightness;
    int target_brightness;
} klh_light_view_t;

typedef struct {
    klh_light_view_t light;
    klh_light_view_t restore;
    char light_command_id[KLH_COMMAND_ID_SIZE];
    bool fan_power;
    char fan_command_id[KLH_COMMAND_ID_SIZE];
} klh_state_t;

/* Decode a bounded, not necessarily NUL-terminated payload. NULL means valid.
 * Preserve a valid commandId even when rejecting the rest of the command. */
const char *klh_parse(klh_device_t device, const char *json, size_t size, klh_command_t *out);
/* Apply to a candidate snapshot; the caller commits it only after hardware success. */
const char *klh_apply(klh_state_t *state, const klh_command_t *command, int64_t now_us);
bool klh_tick(klh_state_t *state, int64_t now_us);
bool klh_timestamp(time_t now, char out[32]);
cJSON *klh_state_json(klh_device_t device, const klh_state_t *state, const char *timestamp);
cJSON *klh_ack_json(klh_device_t device, const char *command_id, const char *result,
                    const char *reason, const klh_state_t *state, const char *timestamp);
