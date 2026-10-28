#include "light_model.h"

#include <assert.h>
#include <stdio.h>
#include <string.h>

#define ENVELOPE "\"commandId\":\"room-cmd\",\"issuedAt\":\"2026-10-27T00:00:00Z\","
#define LIGHT ENVELOPE "\"deviceId\":\"light-01\","

static rl_command_t decode(const char *json)
{
    rl_command_t command;
    const char *error = rl_parse(json, strlen(json), &command);
    if (error) fprintf(stderr, "Unexpected rejection: %s\n", error);
    assert(!error);
    return command;
}

static void rejected(const char *json, const char *reason)
{
    rl_command_t command;
    const char *error = rl_parse(json, strlen(json), &command);
    assert(error && !strcmp(error, reason));
}

static void validation(void)
{
    rejected("{" ENVELOPE "\"deviceId\":\"light-00\",\"type\":\"on\"}", "device_id_mismatch");
    rejected("{" ENVELOPE "\"deviceId\":\"light-02\",\"type\":\"on\"}", "device_id_mismatch");
    rejected("{" ENVELOPE "\"deviceId\":\"fan-01\",\"type\":\"on\"}", "device_id_mismatch");
    rejected("{" LIGHT "\"type\":\"set_speed\",\"speed\":\"high\"}", "invalid_type");
    rejected("{" LIGHT "\"type\":\"on\",\"brightness\":20}", "on_requires_brightness_100");
    rejected("{" LIGHT "\"type\":\"blink\",\"durationSec\":0}", "invalid_duration_sec");
    rejected("{" LIGHT "\"type\":\"blink\",\"durationSec\":1.5}", "invalid_duration_sec");
    rejected("{" LIGHT "\"type\":\"blink\",\"durationSec\":3601}", "invalid_duration_sec");
    rejected("{" LIGHT "\"type\":\"fadeout\",\"brightness\":0,\"durationSec\":3}", "invalid_brightness");
    rejected("{" LIGHT "\"type\":\"fadeout\",\"brightness\":101,\"durationSec\":3}", "invalid_brightness");
    rejected("{" LIGHT "\"type\":\"fadeout\",\"brightness\":20}", "invalid_duration_sec");
    rejected("{\"commandId\":\"x\",\"deviceId\":\"light-01\",\"type\":\"on\"}", "missing_issued_at");
    rejected("{\"commandId\":\"\"}", "invalid_command_id");
    rejected("{" LIGHT "\"type\":\"on\"}junk", "invalid_json");
    rejected("[]", "invalid_json");
    rejected("{broken}", "invalid_json");
    char nested[81];
    memset(nested, '[', 40);
    memset(nested + 40, ']', 40);
    nested[80] = 0;
    rejected(nested, "invalid_json");
    rl_command_t command;
    char nul[] = "{}\0junk";
    assert(rl_parse(nul, sizeof(nul) - 1, &command));
    char oversized[RL_MAX_PAYLOAD + 1];
    memset(oversized, ' ', sizeof(oversized));
    assert(rl_parse(oversized, sizeof(oversized), &command));
    const char *unknown = "{" LIGHT "\"type\":\"unsupported\"}";
    assert(rl_parse(unknown, strlen(unknown), &command));
    assert(!strcmp(command.id, "room-cmd"));
    const char *valid = "{" LIGHT "\"type\":\"on\"} \n";
    char exact[256];
    memcpy(exact, valid, strlen(valid));
    assert(!rl_parse(exact, strlen(valid), &command));
}

static void animations(void)
{
    rl_state_t state = {0};
    rl_command_t on = decode("{" LIGHT "\"type\":\"on\",\"brightness\":100}");
    rl_command_t off = decode("{" LIGHT "\"type\":\"off\"}");
    rl_command_t fade = decode("{" LIGHT "\"type\":\"fadeout\",\"brightness\":20,\"durationSec\":3}");
    rl_command_t blink = decode("{" LIGHT "\"type\":\"blink\",\"durationSec\":2}");
    assert(!strcmp(rl_apply(&state, &fade, 0), "light_is_off"));
    assert(!rl_apply(&state, &on, 0));
    assert(state.light.power && state.light.brightness == 100);
    assert(!rl_apply(&state, &fade, 0));
    int previous = 100;
    for (int64_t now = 20000; now <= 3000000; now += 20000) {
        rl_tick(&state, now);
        assert(state.light.power && state.light.brightness <= previous);
        assert(state.light.brightness >= 20);
        previous = state.light.brightness;
    }
    assert(state.light.brightness == 20 && state.light.mode == RL_STEADY);
    assert(!rl_tick(&state, 9000000));

    /* A blink returns to the previous dimmed brightness. */
    assert(!rl_apply(&state, &blink, 10000000));
    assert(rl_tick(&state, 10500000));
    assert(!state.light.power && state.light.brightness == 0);
    assert(rl_tick(&state, 12000000));
    assert(state.light.power && state.light.brightness == 20);
    assert(!rl_apply(&state, &off, 13000000));
    assert(!state.light.power && state.light.brightness == 0 && state.light.mode == RL_STEADY);
    assert(!rl_apply(&state, &blink, 14000000));
    assert(rl_tick(&state, 16000000));
    assert(!state.light.power && state.light.brightness == 0);

    /* Explicit OFF interrupts fade without any delayed restoration. */
    assert(!rl_apply(&state, &on, 17000000));
    assert(!rl_apply(&state, &fade, 17000000));
    rl_tick(&state, 18000000);
    assert(!rl_apply(&state, &off, 18000000));
    assert(!rl_tick(&state, 21000000));
    assert(!state.light.power && state.light.brightness == 0);

    /* Blink restores an interrupted fade using the original timeline. */
    assert(!rl_apply(&state, &on, 22000000));
    assert(!rl_apply(&state, &fade, 22000000));
    assert(!rl_apply(&state, &blink, 22500000));
    assert(rl_tick(&state, 24500000));
    assert(state.light.mode == RL_FADING && state.light.brightness == 34);
    assert(rl_tick(&state, 25000000));
    assert(state.light.brightness == 20);

    assert(!rl_apply(&state, &blink, 26000000));
    assert(!rl_apply(&state, &off, 26500000));
    assert(!rl_tick(&state, 29000000));
    assert(!state.light.power && state.light.brightness == 0);
    assert(!rl_apply(&state, &on, 30000000));
    assert(!rl_apply(&state, &fade, 30000000));
    assert(!rl_apply(&state, &on, 31000000));
    assert(!rl_tick(&state, 34000000));
    assert(state.light.power && state.light.brightness == 100);
}

static void messages(void)
{
    rl_state_t state = {0};
    char timestamp[32];
    assert(!rl_timestamp(0, timestamp));
    assert(rl_timestamp(1793059200, timestamp));
    assert(!strcmp(timestamp, "2026-10-27T00:00:00Z"));
    cJSON *root = rl_state_json(&state, timestamp);
    assert(root);
    cJSON *control = cJSON_GetObjectItemCaseSensitive(root, "lastControl");
    assert(!strcmp(cJSON_GetObjectItemCaseSensitive(control, "publisher")->valuestring, "user"));
    assert(!cJSON_GetObjectItemCaseSensitive(control, "commandId"));
    cJSON_Delete(root);

    rl_command_t on = decode("{" LIGHT "\"type\":\"on\"}");
    assert(!rl_apply(&state, &on, 0));
    root = rl_ack_json(on.id, "applied", NULL, &state, timestamp);
    assert(root);
    assert(!strcmp(cJSON_GetObjectItemCaseSensitive(root, "commandId")->valuestring, "room-cmd"));
    assert(!strcmp(cJSON_GetObjectItemCaseSensitive(root, "result")->valuestring, "applied"));
    cJSON *snapshot = cJSON_GetObjectItemCaseSensitive(root, "state");
    assert(cJSON_GetObjectItemCaseSensitive(snapshot, "brightness")->valueint == 100);
    assert(!cJSON_GetObjectItemCaseSensitive(snapshot, "speed"));
    control = cJSON_GetObjectItemCaseSensitive(snapshot, "lastControl");
    assert(!strcmp(cJSON_GetObjectItemCaseSensitive(control, "publisher")->valuestring, "api"));
    assert(!strcmp(cJSON_GetObjectItemCaseSensitive(control, "commandId")->valuestring, on.id));
    cJSON_Delete(root);
}

int main(void)
{
    validation();
    animations();
    messages();
    puts("PASS: room device validation, monotonic fadeout, blink restoration, immediate OFF, interrupted animations, JSON and UTC timestamps");
    return 0;
}
