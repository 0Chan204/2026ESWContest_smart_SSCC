#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <time.h>
#include "cJSON.h"

#define INDUCTION_COMMAND_ID_SIZE 128
#define INDUCTION_MAX_COMMAND_SIZE 1024
#define INDUCTION_BURNER_ID "burner-1"

typedef enum { INDUCTION_OFF, INDUCTION_ON, INDUCTION_OVERHEATED, INDUCTION_COOLING } induction_mode_t;
typedef enum {
    INDUCTION_TURN_ON, INDUCTION_TURN_OFF, INDUCTION_SET_LEVEL,
    INDUCTION_SELECT_OFF, INDUCTION_SELECT_ON, INDUCTION_SELECT_OVERHEAT
} induction_action_t;
typedef enum { INDUCTION_USER, INDUCTION_API, INDUCTION_SYSTEM } induction_publisher_t;

typedef struct {
    char command_id[INDUCTION_COMMAND_ID_SIZE];
    induction_action_t action;
    int level; /* 0 means use default_level for turn_on. */
    bool local;
} induction_command_t;

typedef struct {
    induction_mode_t mode;
    int level;
    double temperature;
    uint64_t active_sec;
    int64_t started_us;
    int64_t updated_us;
    bool alarm;
    induction_publisher_t publisher;
    char command_id[INDUCTION_COMMAND_ID_SIZE];
} induction_state_t;

/* Transport supplies length bytes followed by NUL. NULL means valid. */
const char *induction_parse_command(const char *json, size_t length, induction_command_t *command);
void induction_init(induction_state_t *state, int64_t now_us);
/* Call tick before apply; rejected commands leave the state unchanged. */
const char *induction_apply(induction_state_t *state, const induction_command_t *command,
                            int64_t now_us, int default_level);
/* Updates temperature/time; returns true only for mode/alarm transitions. */
bool induction_tick(induction_state_t *state, int64_t now_us);
/* Random walk by up to +/-3 C, bounded to 100-120 C (on) / 150-180 C (overheated). */
void induction_sample_temperature(induction_state_t *state, uint32_t random_value);
/* Console aliases are scenario selections; the MQTT parser never accepts these actions. */
bool induction_console_action(const char *input, induction_action_t *action);
const char *induction_mode_name(induction_mode_t mode);
bool induction_timestamp(time_t now, char output[32]);
cJSON *induction_burner_json(const induction_state_t *state);
cJSON *induction_state_json(const induction_state_t *state, const char *timestamp);
cJSON *induction_ack_json(const char *command_id, const char *result, const char *reason,
                          const induction_state_t *state, const char *timestamp);
