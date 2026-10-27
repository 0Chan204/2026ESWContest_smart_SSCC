#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <time.h>
#include "cJSON.h"

#define TLF_COMMAND_ID_SIZE 128
#define TLF_MAX_PAYLOAD 1024
#define TLF_LIGHT_ID "light-00"
#define TLF_FAN_ID "fan-02"
#define TLF_LIGHT_BASE "home/toilet/light/" TLF_LIGHT_ID
#define TLF_FAN_BASE "home/toilet/fan/" TLF_FAN_ID

typedef enum { TLF_LIGHT, TLF_FAN } tlf_device_t;
typedef enum { TLF_ON, TLF_OFF, TLF_BLINK, TLF_FADEOUT } tlf_action_t;
typedef enum { TLF_STEADY, TLF_BLINKING, TLF_FADING } tlf_mode_t;

typedef struct {
    tlf_device_t device;
    char id[TLF_COMMAND_ID_SIZE];
    tlf_action_t action;
    int brightness;
    int duration_sec;
} tlf_command_t;

typedef struct {
    bool power;
    int brightness;
    tlf_mode_t mode;
    int64_t start_us;
    int64_t end_us;
    int start_brightness;
    int target_brightness;
} tlf_light_view_t;

typedef struct {
    tlf_light_view_t light;
    tlf_light_view_t restore;
    char light_command_id[TLF_COMMAND_ID_SIZE];
    bool fan_power;
    char fan_command_id[TLF_COMMAND_ID_SIZE];
} tlf_state_t;

/* Decode a bounded, not necessarily NUL-terminated payload. NULL means valid.
 * Preserve a valid commandId even when rejecting the rest of the command. */
const char *tlf_parse(tlf_device_t device, const char *json, size_t size, tlf_command_t *out);
/* Apply to a candidate snapshot; the caller commits it only after hardware success. */
const char *tlf_apply(tlf_state_t *state, const tlf_command_t *command, int64_t now_us);
bool tlf_tick(tlf_state_t *state, int64_t now_us);
bool tlf_timestamp(time_t now, char out[32]);
cJSON *tlf_state_json(tlf_device_t device, const tlf_state_t *state, const char *timestamp);
cJSON *tlf_ack_json(tlf_device_t device, const char *command_id, const char *result,
                    const char *reason, const tlf_state_t *state, const char *timestamp);
