#include "device_model.h"

#include <assert.h>
#include <stdio.h>
#include <string.h>

#define ENVELOPE "\"commandId\":\"c1\",\"issuedAt\":\"2026-10-27T00:00:00Z\","
#define LIGHT ENVELOPE "\"deviceId\":\"light-00\","
#define FAN ENVELOPE "\"deviceId\":\"fan-02\","

static tlf_command_t decode(tlf_device_t device, const char *json)
{
    tlf_command_t command;
    const char *error = tlf_parse(device, json, strlen(json), &command);
    if (error) fprintf(stderr, "Unexpected rejection: %s\n", error);
    assert(!error);
    return command;
}

static void invalid(tlf_device_t device, const char *json, const char *expected)
{
    tlf_command_t command;
    const char *error = tlf_parse(device, json, strlen(json), &command);
    assert(error && !strcmp(error, expected));
}

static void validation(void)
{
    invalid(TLF_LIGHT, "{" LIGHT "\"type\":\"on\"}junk", "invalid_json");
    invalid(TLF_LIGHT, "{" FAN "\"type\":\"on\"}", "device_id_mismatch");
    invalid(TLF_FAN, "{" LIGHT "\"type\":\"on\"}", "device_id_mismatch");
    invalid(TLF_FAN, "{" FAN "\"type\":\"set_speed\",\"speed\":\"high\"}", "unsupported_speed_control");
    invalid(TLF_FAN, "{" FAN "\"type\":\"blink\",\"durationSec\":1}", "invalid_type");
    invalid(TLF_LIGHT, "{" LIGHT "\"type\":\"on\",\"brightness\":20}", "on_requires_brightness_100");
    invalid(TLF_LIGHT, "{" LIGHT "\"type\":\"blink\",\"durationSec\":0}", "invalid_duration_sec");
    invalid(TLF_LIGHT, "{" LIGHT "\"type\":\"blink\",\"durationSec\":1.5}", "invalid_duration_sec");
    invalid(TLF_LIGHT, "{" LIGHT "\"type\":\"blink\",\"durationSec\":3601}", "invalid_duration_sec");
    invalid(TLF_LIGHT, "{" LIGHT "\"type\":\"fadeout\",\"brightness\":0,\"durationSec\":3}", "invalid_brightness");
    invalid(TLF_LIGHT, "{" LIGHT "\"type\":\"fadeout\",\"brightness\":101,\"durationSec\":3}", "invalid_brightness");
    invalid(TLF_LIGHT, "{\"commandId\":\"c\",\"deviceId\":\"light-00\",\"type\":\"on\"}", "missing_issued_at");
    invalid(TLF_LIGHT, "{\"commandId\":\"\"}", "invalid_command_id");
    invalid(TLF_LIGHT, "[]", "invalid_json");
    invalid(TLF_LIGHT, "{broken}", "invalid_json");
    char nested[81];
    memset(nested, '[', 40);
    memset(nested + 40, ']', 40);
    nested[80] = 0;
    invalid(TLF_LIGHT, nested, "invalid_json");
    tlf_command_t command;
    char nul[] = "{}\0junk";
    assert(tlf_parse(TLF_LIGHT, nul, sizeof(nul) - 1, &command));
    char oversized[TLF_MAX_PAYLOAD + 1];
    memset(oversized, ' ', sizeof(oversized));
    assert(tlf_parse(TLF_LIGHT, oversized, sizeof(oversized), &command));
    const char *rejected = "{" LIGHT "\"type\":\"unsupported\"}";
    assert(tlf_parse(TLF_LIGHT, rejected, strlen(rejected), &command));
    assert(!strcmp(command.id, "c1"));
    const char *valid = "{" LIGHT "\"type\":\"on\"} \n";
    char exact[256];
    memcpy(exact, valid, strlen(valid));
    assert(!tlf_parse(TLF_LIGHT, exact, strlen(valid), &command));
}

static void behavior(void)
{
    tlf_state_t state = {0};
    tlf_command_t on = decode(TLF_LIGHT, "{" LIGHT "\"type\":\"on\",\"brightness\":100}");
    tlf_command_t off = decode(TLF_LIGHT, "{" LIGHT "\"type\":\"off\"}");
    tlf_command_t fade = decode(TLF_LIGHT, "{" LIGHT "\"type\":\"fadeout\",\"brightness\":20,\"durationSec\":3}");
    tlf_command_t blink = decode(TLF_LIGHT, "{" LIGHT "\"type\":\"blink\",\"durationSec\":2}");
    assert(!strcmp(tlf_apply(&state, &fade, 0), "light_is_off"));
    assert(!tlf_apply(&state, &on, 0));
    assert(state.light.power && state.light.brightness == 100);
    assert(!tlf_apply(&state, &fade, 0));
    assert(tlf_tick(&state, 1500000));
    assert(state.light.power && state.light.brightness == 60 && state.light.mode == TLF_FADING);
    assert(tlf_tick(&state, 3000000));
    assert(state.light.power && state.light.brightness == 20 && state.light.mode == TLF_STEADY);
    assert(!tlf_tick(&state, 9000000));
    assert(!tlf_apply(&state, &blink, 10000000));
    assert(tlf_tick(&state, 10500000));
    assert(!state.light.power && state.light.brightness == 0);
    assert(tlf_tick(&state, 12000000));
    assert(state.light.power && state.light.brightness == 20);
    assert(!tlf_apply(&state, &off, 13000000));
    assert(!state.light.power && state.light.brightness == 0 && state.light.mode == TLF_STEADY);
    assert(!tlf_apply(&state, &blink, 14000000));
    assert(tlf_tick(&state, 16000000));
    assert(!state.light.power && state.light.brightness == 0);

    /* Explicit OFF interrupts fade without a delayed restoration. */
    assert(!tlf_apply(&state, &on, 17000000));
    assert(!tlf_apply(&state, &fade, 17000000));
    tlf_tick(&state, 18000000);
    assert(!tlf_apply(&state, &off, 18000000));
    assert(!tlf_tick(&state, 21000000));
    assert(!state.light.power && state.light.brightness == 0);

    /* Blink restores an interrupted fade using its original timeline. */
    assert(!tlf_apply(&state, &on, 22000000));
    assert(!tlf_apply(&state, &fade, 22000000));
    assert(!tlf_apply(&state, &blink, 22500000));
    assert(tlf_tick(&state, 24500000));
    assert(state.light.mode == TLF_FADING && state.light.brightness == 34);
    assert(tlf_tick(&state, 25000000));
    assert(state.light.brightness == 20);

    /* Fan commands leave the light animation running independently. */
    assert(!tlf_apply(&state, &on, 26000000));
    assert(!tlf_apply(&state, &fade, 26000000));
    tlf_light_view_t light = state.light;
    tlf_command_t fan_on = decode(TLF_FAN, "{" FAN "\"type\":\"on\"}");
    assert(!tlf_apply(&state, &fan_on, 27000000));
    assert(state.fan_power && !memcmp(&light, &state.light, sizeof(light)));
    tlf_tick(&state, 29000000);
    assert(state.fan_power && state.light.brightness == 20);
    tlf_command_t fan_off = decode(TLF_FAN, "{" FAN "\"type\":\"off\"}");
    assert(!tlf_apply(&state, &fan_off, 30000000));
    assert(!state.fan_power && state.light.power);
    assert(!tlf_apply(&state, &on, 31000000));
    assert(state.light.brightness == 100);
}

static void json_output(void)
{
    tlf_state_t state = {0};
    char timestamp[32];
    assert(!tlf_timestamp(0, timestamp));
    assert(tlf_timestamp(1793059200, timestamp));
    assert(!strcmp(timestamp, "2026-10-27T00:00:00Z"));
    cJSON *root = tlf_state_json(TLF_LIGHT, &state, timestamp);
    assert(root);
    cJSON *control = cJSON_GetObjectItemCaseSensitive(root, "lastControl");
    assert(!strcmp(cJSON_GetObjectItemCaseSensitive(control, "publisher")->valuestring, "user"));
    assert(!cJSON_GetObjectItemCaseSensitive(control, "commandId"));
    cJSON_Delete(root);
    snprintf(state.fan_command_id, sizeof(state.fan_command_id), "fan-cmd");
    root = tlf_ack_json(TLF_FAN, "fan-cmd", "rejected", "unsupported_speed_control", &state, timestamp);
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
