#include "water_model.h"
#include "water_led.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>

static wp_command_t parse(const char *payload, const char *expected)
{
    wp_command_t command;
    const char *error = wp_parse(payload, strlen(payload), &command);
    assert(expected ? error && !strcmp(error, expected) : !error);
    return command;
}

int main(void)
{
    uint8_t frame[WP_LED_FRAME_BYTES];
    const uint8_t expected[3][3] = {{0,255,0}, {0,0,255}, {0,0,255}};
    for (unsigned kind = WP_HOT; kind <= WP_PURIFIED; ++kind) {
    for (unsigned on = 0; on < 2; ++on) {
        wp_led_encode(on, (wp_water_type_t)kind, 255, frame);
        for (unsigned i = 0; i < WP_LED_RESET_BYTES; ++i) {
            assert(frame[i] == 0);
            assert(frame[WP_LED_FRAME_BYTES - 1 - i] == 0);
        }
        for (unsigned channel = 0; channel < WP_LED_COUNT * 3; ++channel) {
            uint8_t decoded = 0;
            for (unsigned pair = 0; pair < 4; ++pair) {
                uint8_t encoded = frame[WP_LED_RESET_BYTES + channel * 4 + pair];
                uint8_t high = encoded >> 4, low = encoded & 15;
                assert((high == 8 || high == 14) && (low == 8 || low == 14));
                decoded = (decoded << 2) | ((high == 14) << 1) | (low == 14);
            }
            assert(decoded == (on ? expected[kind][channel % 3] : 0));
        }
    }
    }
    wp_state_t s;
    wp_init(&s);
    assert(!s.dispensing && s.selected_ml == 120 && s.water_type == WP_PURIFIED);
    assert(!wp_select(&s, 2) && s.selected_ml == 120);
    assert(wp_select(&s, 3) && s.selected_ml == 240);
    assert(wp_select(&s, 3) && s.selected_ml == 360);
    assert(wp_select(&s, 3) && s.selected_ml == 480);
    assert(!wp_select(&s, 3) && s.selected_ml == 480);
    assert(wp_select(&s, 2) && s.selected_ml == 360);
    assert(wp_select(&s, 1) && s.water_type == WP_HOT);
    assert(wp_select(&s, 1) && s.water_type == WP_COLD);
    assert(wp_select(&s, 1) && s.water_type == WP_PURIFIED);
    wp_command_t server = parse("{\"commandId\":\"s-1\",\"issuedAt\":\"2026-10-27T00:00:00Z\",\"deviceId\":\"water-01\",\"type\":\"dispense\",\"amountMl\":2000}", NULL);
    assert(server.amount_ml == 120);
    wp_command_t missing = parse("{\"commandId\":\"s-2\",\"issuedAt\":\"t\",\"deviceId\":\"water-01\",\"type\":\"dispense\"}", NULL);
    assert(missing.amount_ml == 120);
    assert(!wp_apply(&s, &server, false, 1000000, 600, 120));
    assert(s.dispensing && s.target_ml == 120 && s.selected_ml == 360);
    assert(s.deadline_us == 13000000 && !strcmp(s.command_id, "s-1"));
    assert(!wp_select(&s, 1) && !wp_select(&s, 2) && !wp_select(&s, 3));
    assert(!strcmp(wp_apply(&s, &server, false, 2000000, 600, 120), "busy"));
    assert(wp_estimated_ml(&s, 6000000) == 50);
    assert(!wp_tick(&s, 12999999));
    assert(wp_tick(&s, 13000000) && !s.dispensing && s.last_ml == 120);
    assert(!wp_tick(&s, 14000000));
    wp_command_t local = {.action = WP_DISPENSE, .amount_ml = 480};
    assert(!wp_apply(&s, &local, true, 20000000, 600, 120));
    assert(!strcmp(s.publisher, "user") && !s.command_id[0]);
    wp_command_t stop = {.action = WP_STOP};
    assert(!wp_apply(&s, &stop, true, 23500000, 600, 120));
    assert(!s.dispensing && s.last_ml == 35);
    assert(!wp_apply(&s, &stop, true, 30000000, 600, 120) && s.last_ml == 35);
    assert(!strcmp(wp_apply(&s, &local, true, 0, 60, 120), "duration_limit_exceeded"));
    assert(!s.dispensing);
    assert(!strcmp(wp_apply(&s, &local, true, 0, 0, 120), "invalid_flow_configuration"));
    local.amount_ml = 0;
    assert(!strcmp(wp_apply(&s, &local, true, 0, 600, 120), "invalid_amount_ml"));
    local.amount_ml = 1;
    assert(!wp_apply(&s, &local, true, 0, 700, 120));
    assert(s.deadline_us == 85715); /* Round up: never terminate earlier than the estimate. */
    assert(wp_tick(&s, 85715) && s.last_ml == 1);
    cJSON *root = wp_state_json(&s, "2026-10-27T00:00:00Z");
    assert(root);
    assert(cJSON_IsTrue(cJSON_GetObjectItemCaseSensitive(root, "volumeEstimated")));
    assert(cJSON_IsTrue(cJSON_GetObjectItemCaseSensitive(root, "simulated")));
    assert(cJSON_IsFalse(cJSON_GetObjectItemCaseSensitive(root, "temperatureControlAvailable")));
    assert(!strcmp(cJSON_GetObjectItemCaseSensitive(root, "status")->valuestring, "idle"));
    cJSON_Delete(root);
    root = wp_ack_json(server.id, "applied", NULL, &s, "2026-10-27T00:00:00Z");
    assert(root && !strcmp(cJSON_GetObjectItemCaseSensitive(root, "commandId")->valuestring, "s-1"));
    assert(cJSON_IsObject(cJSON_GetObjectItemCaseSensitive(root, "state")));
    cJSON_Delete(root);
    parse("{\"commandId\":\"\"}", "invalid_command_id");
    parse("{\"commandId\":\"x\",\"deviceId\":\"air-01\"}", "device_id_mismatch");
    parse("{\"commandId\":\"x\",\"deviceId\":\"water-01\"}", "missing_issued_at");
    parse("{\"commandId\":\"x\",\"deviceId\":\"water-01\",\"issuedAt\":\"t\",\"type\":\"on\"}", "invalid_type");
    parse("{\"commandId\":\"x\"}garbage", "invalid_json");
    wp_command_t invalid;
    assert(wp_parse("{}\0{}", 5, &invalid));
    assert(wp_parse(NULL, 1, &invalid));
    char large[WP_MAX_PAYLOAD + 1]; memset(large, ' ', sizeof(large));
    assert(wp_parse(large, sizeof(large), &invalid));
    char timestamp[32]; assert(!wp_timestamp(0, timestamp));
    assert(wp_timestamp(1793059200, timestamp) && strchr(timestamp, 'Z'));
    puts("PASS: eight red/blue/off LED frames at 255, selections, fixed 120mL server requests, timing, stop estimate, busy rejection, limits and JSON/ACK");
}
