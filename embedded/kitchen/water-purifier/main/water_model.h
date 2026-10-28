#pragma once
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <time.h>
#include "cJSON.h"

#define WP_COMMAND_ID_SIZE 128
#define WP_MAX_PAYLOAD 1024
#define WP_DEVICE_ID "water-01"
#define WP_TOPIC_BASE "home/kitchen/water_purifier/" WP_DEVICE_ID
typedef enum { WP_DISPENSE, WP_STOP } wp_action_t;
typedef enum { WP_HOT, WP_COLD, WP_PURIFIED } wp_water_type_t;
typedef struct {
    char id[WP_COMMAND_ID_SIZE];
    wp_action_t action;
    int amount_ml;
} wp_command_t;
typedef struct {
    bool dispensing;
    wp_water_type_t water_type;
    int selected_ml;
    int target_ml, last_ml;
    int flow_ml_per_min;
    int64_t started_us, deadline_us;
    const char *publisher;
    char command_id[WP_COMMAND_ID_SIZE];
} wp_state_t;
void wp_init(wp_state_t *state);
bool wp_select(wp_state_t *state, unsigned key);
int wp_estimated_ml(const wp_state_t *state, int64_t now);
bool wp_tick(wp_state_t *state, int64_t now);
const char *wp_apply(wp_state_t *state, const wp_command_t *command, bool local,
                     int64_t now, int flow_ml_per_min, unsigned max_run_sec);
const char *wp_parse(const char *json, size_t size, wp_command_t *out);
bool wp_timestamp(time_t now, char out[32]);
cJSON *wp_state_json(const wp_state_t *state, const char *timestamp);
cJSON *wp_ack_json(const char *command_id, const char *result, const char *reason,
                    const wp_state_t *state, const char *timestamp);
