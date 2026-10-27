#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <time.h>
#include "cJSON.h"

#define WATER_COMMAND_ID_SIZE 128
#define WATER_MAX_COMMAND_SIZE 1024
#define WATER_MAX_AMOUNT_ML 5000

typedef enum { WATER_DISPENSE, WATER_STOP } water_action_t;

typedef struct {
    char command_id[WATER_COMMAND_ID_SIZE];
    water_action_t action;
    int amount_ml;
    bool local;
} water_command_t;

typedef struct {
    bool dispensing;
    bool has_last_amount;
    int last_dispensed_ml;
    int target_ml;
    int flow_ml_sec;
    int64_t started_us;
    char command_id[WATER_COMMAND_ID_SIZE];
    bool local_control;
} water_state_t;

/* The transport supplies length bytes followed by a NUL. NULL means valid. */
const char *water_parse_command(const char *json, size_t length,
                                const char *device_id, water_command_t *command);
/* Rejected commands leave the state unchanged. flow_ml_sec must be positive. */
const char *water_apply(water_state_t *state, const water_command_t *command,
                        int64_t now_us, int flow_ml_sec);
bool water_tick(water_state_t *state, int64_t now_us);
bool water_timestamp(time_t now, char output[32]);
cJSON *water_state_json(const water_state_t *state, const char *timestamp);
