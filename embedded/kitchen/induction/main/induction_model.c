#include "induction_model.h"
#include <math.h>
#include <stdio.h>
#include <string.h>

const char *induction_mode_name(device_state_t mode)
{
    static const char *names[] = {"off", "on", "cooling", "overheated"};
    return names[mode];
}
void induction_init(induction_state_t *s)
{
    memset(s, 0, sizeof(*s));
    s->temperature = 25;
    strcpy(s->publisher, "user");
}
static void transition(induction_state_t *s, device_state_t mode, int64_t now)
{
    if (s->mode == mode) return;
    if (mode == ST_ON) s->started_us = now;
    else { s->level = 0; s->started_us = 0; s->active_sec = 0; }
    s->mode = mode;
}
bool induction_apply(induction_state_t *s, const induction_command_t *c,
                     bool local, unsigned default_level, int64_t now)
{
    if (c->type > CMD_LEVEL || c->level > 9 ||
        (c->type == CMD_LEVEL && !local && !c->level) ||
        (s->mode == ST_OVERHEATED && c->type != CMD_OFF)) return false;
    if (c->type == CMD_OFF) {
        /* OFF must not clear the overheat latch. */
        if (s->mode != ST_OVERHEATED)
            transition(s, s->temperature_valid && s->temperature > 30 ? ST_COOLING : ST_OFF, now);
        s->level = 0;
    } else {
        transition(s, ST_ON, now);
        s->level = c->type == CMD_LEVEL ? c->level :
                   (c->level ? c->level : default_level);
    }
    snprintf(s->publisher, sizeof(s->publisher), "%s", local ? "user" : "api");
    snprintf(s->command_id, sizeof(s->command_id), "%s", local ? "" : c->id);
    s->revision++;
    return true;
}
void induction_temperature(induction_state_t *s, float value, bool valid,
                           float enter, float exit, int64_t now)
{
    s->temperature_valid = valid && isfinite(value);
    if (!s->temperature_valid) return;
    s->temperature = value;
    s->temperature_us = now;
    device_state_t before = s->mode;
    if (s->mode == ST_ON && value >= enter) {
        transition(s, ST_OVERHEATED, now);
        s->alarm = true;
    } else if (s->mode == ST_OVERHEATED && value <= exit) {
        transition(s, ST_OFF, now);
        s->alarm = false;
    } else if (s->mode == ST_COOLING && value <= 26) {
        transition(s, ST_OFF, now);
    }
    if (before != s->mode) {
        strcpy(s->publisher, "system");
        s->command_id[0] = 0;
        s->revision++;
    }
}
void induction_tick(induction_state_t *s, int64_t now)
{
    if (s->mode == ST_ON) s->active_sec = (uint32_t)((now - s->started_us) / 1000000);
    if (s->temperature_valid && now - s->temperature_us > 2000000) {
        s->temperature_valid = false;
    }
}
void induction_pixels(const induction_state_t *s, uint8_t max_brightness,
                      uint8_t grb[INDUCTION_LEDS * 3])
{
    memset(grb, 0, INDUCTION_LEDS * 3);
    if (s->mode != ST_ON || !s->level) return;
    unsigned count = s->level <= 2 ? 3 : s->level <= 4 ? 6 : s->level <= 6 ? 9 : 12;
    uint8_t brightness = ((unsigned)max_brightness * s->level + 8) / 9;
    /* Nested masks: 0,4,8 -> +2,6,10 -> +1,5,9 -> +3,7,11.
       All LEDs already lit at a lower level stay lit as power increases. */
    static const uint8_t order[12] = {0,4,8,2,6,10,1,5,9,3,7,11};
    for (unsigned i = 0; i < count; i++) {
        unsigned at = order[i] * 3;
        grb[at] = brightness / 8;
        grb[at + 1] = brightness;
    }
}
