#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <time.h>
#include "cJSON.h"

#define AP_COMMAND_ID_SIZE 128
#define AP_MAX_PAYLOAD 1024
#define AP_DEVICE_ID "air-01"
#define AP_TOPIC_BASE "home/room/air_purifier/" AP_DEVICE_ID

typedef enum { AP_ON, AP_OFF, AP_SET_MODE } ap_action_t;
typedef enum { AP_MANUAL, AP_AUTO } ap_mode_t;
typedef enum { AP_UNKNOWN, AP_GOOD, AP_NORMAL, AP_BAD, AP_VERY_BAD } ap_quality_t;
typedef struct {
    char id[AP_COMMAND_ID_SIZE];
    ap_action_t action;
    ap_mode_t mode;
} ap_command_t;
typedef struct {
    bool power;
    ap_mode_t mode;
    bool sensor_valid, warming_up;
    int raw, adc_mv; /* ADC pin voltage, not the voltage before the divider. */
    bool ppm_valid;
    double ppm; /* Reference CO2-equivalent estimate, not calibrated CO2. */
    ap_quality_t quality;
    const char *publisher;
    char command_id[AP_COMMAND_ID_SIZE];
} ap_state_t;

void ap_init(ap_state_t *state);
const char *ap_parse(const char *json, size_t size, ap_command_t *out);
/* Candidates are committed by the caller only after relay output succeeds. */
const char *ap_apply(ap_state_t *state, const ap_command_t *command);
void ap_sample(ap_state_t *state, bool valid, int raw, int adc_mv,
               int64_t uptime_us, unsigned warmup_sec, int good_raw, int bad_raw, int very_bad_raw);
bool ap_automatic(ap_state_t *state);
void ap_estimate_ppm(ap_state_t *state, int supply_mv, int divider_milli,
                     int rl_ohm, int r0_ohm);
bool ap_timestamp(time_t now, char out[32]);
cJSON *ap_state_json(const ap_state_t *state, const char *timestamp);
cJSON *ap_ack_json(const char *command_id, const char *result, const char *reason,
                    const ap_state_t *state, const char *timestamp);
