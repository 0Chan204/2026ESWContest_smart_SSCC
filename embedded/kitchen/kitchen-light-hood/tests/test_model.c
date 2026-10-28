#include "device_model.h"

#include <assert.h>
#include <stdio.h>
#include <string.h>

#define ENVELOPE "\"commandId\":\"c1\",\"issuedAt\":\"2026-10-27T00:00:00Z\","
#define LIGHT ENVELOPE "\"deviceId\":\"light-02\","
#define FAN ENVELOPE "\"deviceId\":\"fan-01\","

static klh_command_t decode(klh_device_t device, const char *json)
{
    klh_command_t command;
    const char *error = klh_parse(device, json, strlen(json), &command);
    if (error) fprintf(stderr, "Unexpected rejection: %s\n", error);
    assert(!error);
    return command;
}

static void invalid(klh_device_t device, const char *json, const char *expected)
{
    klh_command_t command;
    const char *error = klh_parse(device, json, strlen(json), &command);
    assert(error && !strcmp(error, expected));
}

static void validation(void)
{
    /* Other rooms' device IDs must never operate the kitchen outputs. */
    invalid(KLH_LIGHT, "{" ENVELOPE "\"deviceId\":\"light-00\",\"type\":\"on\"}", "device_id_mismatch");
    invalid(KLH_LIGHT, "{" ENVELOPE "\"deviceId\":\"light-01\",\"type\":\"on\"}", "device_id_mismatch");
    invalid(KLH_FAN, "{" ENVELOPE "\"deviceId\":\"fan-02\",\"type\":\"on\"}", "device_id_mismatch");
    invalid(KLH_LIGHT, "{" LIGHT "\"type\":\"on\"}junk", "invalid_json");
    invalid(KLH_LIGHT, "{" FAN "\"type\":\"on\"}", "device_id_mismatch");
    invalid(KLH_FAN, "{" LIGHT "\"type\":\"on\"}", "device_id_mismatch");
    invalid(KLH_FAN, "{" FAN "\"type\":\"set_speed\",\"speed\":\"high\"}", "unsupported_speed_control");
    invalid(KLH_FAN, "{" FAN "\"type\":\"blink\",\"durationSec\":1}", "invalid_type");
    invalid(KLH_LIGHT, "{" LIGHT "\"type\":\"on\",\"brightness\":20}", "on_requires_brightness_100");
    invalid(KLH_LIGHT, "{" LIGHT "\"type\":\"blink\",\"durationSec\":0}", "invalid_duration_sec");
    invalid(KLH_LIGHT, "{" LIGHT "\"type\":\"blink\",\"durationSec\":1.5}", "invalid_duration_sec");
    invalid(KLH_LIGHT, "{" LIGHT "\"type\":\"blink\",\"durationSec\":3601}", "invalid_duration_sec");
    invalid(KLH_LIGHT, "{" LIGHT "\"type\":\"fadeout\",\"brightness\":0,\"durationSec\":3}", "invalid_brightness");
    invalid(KLH_LIGHT, "{" LIGHT "\"type\":\"fadeout\",\"brightness\":101,\"durationSec\":3}", "invalid_brightness");
    invalid(KLH_LIGHT, "{\"commandId\":\"c\",\"deviceId\":\"light-02\",\"type\":\"on\"}", "missing_issued_at");
    invalid(KLH_LIGHT, "{\"commandId\":\"\"}", "invalid_command_id");
    invalid(KLH_LIGHT, "[]", "invalid_json");
    invalid(KLH_LIGHT, "{broken}", "invalid_json");
    char nested[81];
    memset(nested, '[', 40);
    memset(nested + 40, ']', 40);
    nested[80] = 0;
    invalid(KLH_LIGHT, nested, "invalid_json");
    klh_command_t command;
    char nul[] = "{}\0junk";
    assert(klh_parse(KLH_LIGHT, nul, sizeof(nul) - 1, &command));
    char oversized[KLH_MAX_PAYLOAD + 1];
    memset(oversized, ' ', sizeof(oversized));
    assert(klh_parse(KLH_LIGHT, oversized, sizeof(oversized), &command));
    const char *rejected = "{" LIGHT "\"type\":\"unsupported\"}";
    assert(klh_parse(KLH_LIGHT, rejected, strlen(rejected), &command));
    assert(!strcmp(command.id, "c1"));
    const char *valid = "{" LIGHT "\"type\":\"on\"} \n";
    char exact[256];
    memcpy(exact, valid, strlen(valid));
    assert(!klh_parse(KLH_LIGHT, exact, strlen(valid), &command));
}

static void behavior(void)
{
    klh_state_t state = {0};
    klh_command_t on = decode(KLH_LIGHT, "{" LIGHT "\"type\":\"on\",\"brightness\":100}");
    klh_command_t off = decode(KLH_LIGHT, "{" LIGHT "\"type\":\"off\"}");
    klh_command_t fade = decode(KLH_LIGHT, "{" LIGHT "\"type\":\"fadeout\",\"brightness\":20,\"durationSec\":3}");
    klh_command_t blink = decode(KLH_LIGHT, "{" LIGHT "\"type\":\"blink\",\"durationSec\":2}");
    assert(!strcmp(klh_apply(&state, &fade, 0), "light_is_off"));
    assert(!klh_apply(&state, &on, 0));
    assert(state.light.power && state.light.brightness == 100);
    assert(!klh_apply(&state, &fade, 0));
    assert(klh_tick(&state, 1500000));
    assert(state.light.power && state.light.brightness == 60 && state.light.mode == KLH_FADING);
    assert(klh_tick(&state, 3000000));
    assert(state.light.power && state.light.brightness == 20 && state.light.mode == KLH_STEADY);
    assert(!klh_tick(&state, 9000000));
    assert(!klh_apply(&state, &blink, 10000000));
    assert(klh_tick(&state, 10500000));
    assert(!state.light.power && state.light.brightness == 0);
    assert(klh_tick(&state, 12000000));
    assert(state.light.power && state.light.brightness == 20);
    assert(!klh_apply(&state, &off, 13000000));
    assert(!state.light.power && state.light.brightness == 0 && state.light.mode == KLH_STEADY);
    assert(!klh_apply(&state, &blink, 14000000));
    assert(klh_tick(&state, 16000000));
    assert(!state.light.power && state.light.brightness == 0);

    /* Explicit OFF interrupts fade without a delayed restoration. */
    assert(!klh_apply(&state, &on, 17000000));
    assert(!klh_apply(&state, &fade, 17000000));
    klh_tick(&state, 18000000);
    assert(!klh_apply(&state, &off, 18000000));
    assert(!klh_tick(&state, 21000000));
    assert(!state.light.power && state.light.brightness == 0);

    /* Blink restores an interrupted fade using its original timeline. */
    assert(!klh_apply(&state, &on, 22000000));
    assert(!klh_apply(&state, &fade, 22000000));
    assert(!klh_apply(&state, &blink, 22500000));
    assert(klh_tick(&state, 24500000));
    assert(state.light.mode == KLH_FADING && state.light.brightness == 34);
    assert(klh_tick(&state, 25000000));
    assert(state.light.brightness == 20);

    /* Fan commands leave the light animation running independently. */
    assert(!klh_apply(&state, &on, 26000000));
    assert(!klh_apply(&state, &fade, 26000000));
    klh_light_view_t light = state.light;
    klh_command_t fan_on = decode(KLH_FAN, "{" FAN "\"type\":\"on\"}");
    assert(!klh_apply(&state, &fan_on, 27000000));
    assert(state.fan_power && !memcmp(&light, &state.light, sizeof(light)));
    klh_tick(&state, 29000000);
    assert(state.fan_power && state.light.brightness == 20);
    klh_command_t fan_off = decode(KLH_FAN, "{" FAN "\"type\":\"off\"}");
    assert(!klh_apply(&state, &fan_off, 30000000));
    assert(!state.fan_power && state.light.power);
    assert(!klh_apply(&state, &on, 31000000));
    assert(state.light.brightness == 100);

    /* OFF during a blink must not restore the previously lit state later. */
    assert(!klh_apply(&state, &blink, 32000000));
    assert(!klh_apply(&state, &off, 32500000));
    assert(!klh_tick(&state, 35000000));
    assert(!state.light.power && state.light.brightness == 0);

    /* A new ON cancels a pending saving transition and stays at full brightness. */
    assert(!klh_apply(&state, &on, 36000000));
    assert(!klh_apply(&state, &fade, 36000000));
    assert(!klh_apply(&state, &on, 37000000));
    assert(!klh_tick(&state, 40000000));
    assert(state.light.power && state.light.brightness == 100);
}

static void json_output(void)
{
    klh_state_t state = {0};
    char timestamp[32];
    assert(!klh_timestamp(0, timestamp));
    assert(klh_timestamp(1793059200, timestamp));
    assert(!strcmp(timestamp, "2026-10-27T00:00:00Z"));
    cJSON *root = klh_state_json(KLH_LIGHT, &state, timestamp);
    assert(root);
    cJSON *control = cJSON_GetObjectItemCaseSensitive(root, "lastControl");
    assert(!strcmp(cJSON_GetObjectItemCaseSensitive(control, "publisher")->valuestring, "user"));
    assert(!cJSON_GetObjectItemCaseSensitive(control, "commandId"));
    cJSON_Delete(root);
    snprintf(state.fan_command_id, sizeof(state.fan_command_id), "fan-cmd");
    root = klh_ack_json(KLH_FAN, "fan-cmd", "rejected", "unsupported_speed_control", &state, timestamp);
    assert(root);
    assert(!strcmp(cJSON_GetObjectItemCaseSensitive(root, "commandId")->valuestring, "fan-cmd"));
    assert(!strcmp(cJSON_GetObjectItemCaseSensitive(root, "result")->valuestring, "rejected"));
    cJSON *snapshot = cJSON_GetObjectItemCaseSensitive(root, "state");
    assert(!cJSON_GetObjectItemCaseSensitive(snapshot, "brightness"));
    assert(cJSON_IsFalse(cJSON_GetObjectItemCaseSensitive(snapshot, "speedControllable")));
    control = cJSON_GetObjectItemCaseSensitive(snapshot, "lastControl");
    assert(!strcmp(cJSON_GetObjectItemCaseSensitive(control, "publisher")->valuestring, "api"));
    cJSON_Delete(root);
}

int main(void)
{
    validation();
    behavior();
    json_output();
    puts("PASS: validation, independent light/fan control, blink restoration, fadeout, immediate OFF, JSON and UTC timestamps");
    return 0;
}
