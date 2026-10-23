#pragma once
#include <stdbool.h>
#include <stdint.h>
#define INDUCTION_LEDS 12
#define COMMAND_MAX_BYTES 1024
/* Any command ID that fits in an accepted JSON message must fit unchanged. */
#define COMMAND_ID_SIZE (COMMAND_MAX_BYTES + 1)

typedef enum { ST_OFF, ST_ON, ST_COOLING, ST_OVERHEATED } device_state_t;
typedef enum { CMD_ON, CMD_OFF, CMD_LEVEL } command_type_t;
typedef struct {
    device_state_t mode;
    unsigned level;
    float temperature;
    bool temperature_valid;
    bool alarm;
    uint32_t active_sec;
    int64_t started_us;
    int64_t temperature_us;
    uint32_t revision;
    char publisher[8];
    char command_id[COMMAND_ID_SIZE];
} induction_state_t;
typedef struct {
    command_type_t type;
    unsigned level; /* 0 for ON without a supplied level */
    char id[COMMAND_ID_SIZE];
} induction_command_t;

void induction_init(induction_state_t *s);
bool induction_apply(induction_state_t *s, const induction_command_t *c,
                     bool local, unsigned default_level, int64_t now);
void induction_temperature(induction_state_t *s, float value, bool valid,
                           float enter, float exit, int64_t now);
void induction_tick(induction_state_t *s, int64_t now);
void induction_pixels(const induction_state_t *s, uint8_t max_brightness,
                      uint8_t grb[INDUCTION_LEDS * 3]);
const char *induction_mode_name(device_state_t mode);
