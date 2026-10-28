#include "air_model.h"
#include <assert.h>
#include <math.h>
#include <stdio.h>
#include <string.h>

static ap_command_t parse(const char *payload, const char *expected)
{
    ap_command_t cmd;
    const char *error = ap_parse(payload, strlen(payload), &cmd);
    assert(expected ? error && !strcmp(error, expected) : !error);
    return cmd;
}

static void test_ppm(void)
{
    ap_state_t s;
    ap_init(&s);
    ap_sample(&s, true, 2500, 2500, 200000000, 180, 1500, 2200, 3000);
    ap_estimate_ppm(&s, 5000, 1000, 10000, 10000);
    /* Vout=Vc/2 and RL=R0 gives Rs/R0=1 and exactly the curve coefficient. */
    assert(s.ppm_valid && fabs(s.ppm - 116.6020682) < 0.000001);
    cJSON *json = ap_state_json(&s, "2026-10-27T00:00:00Z");
    cJSON *quality = cJSON_GetObjectItemCaseSensitive(json, "airQuality");
    assert(fabs(cJSON_GetObjectItemCaseSensitive(quality, "ppm")->valuedouble - s.ppm) < 0.000001);
    assert(cJSON_IsTrue(cJSON_GetObjectItemCaseSensitive(quality, "ppmValid")));
    assert(cJSON_IsTrue(cJSON_GetObjectItemCaseSensitive(quality, "ppmEstimated")));
    assert(!strcmp(cJSON_GetObjectItemCaseSensitive(quality, "ppmType")->valuestring, "co2_equivalent"));
    cJSON_Delete(json);
    /* Same sensor voltage through a 1/2 divider must give the same estimate. */
    ap_sample(&s, true, 1250, 1250, 200000000, 180, 1500, 2200, 3000);
    assert(!s.ppm_valid); /* A new sample must invalidate the previous estimate. */
    ap_estimate_ppm(&s, 5000, 2000, 10000, 10000);
    assert(s.ppm_valid && fabs(s.ppm - 116.6020682) < 0.000001);
    ap_estimate_ppm(&s, 5000, 2000, 20000, 10000);
    assert(s.ppm_valid && s.ppm < 116.6020682);
    ap_estimate_ppm(&s, 5000, 2000, 10000, 20000);
    assert(s.ppm_valid && s.ppm > 116.6020682);
    /* Missing calibration, zero voltage, Vout==Vc and Vout>Vc never emit inf/NaN. */
    const int invalid_mv[] = {-1, 0, 2500, 2600};
    for (unsigned i=0; i<sizeof(invalid_mv)/sizeof(invalid_mv[0]); ++i) {
        ap_sample(&s, true, 1200, invalid_mv[i], 200000000, 180, 1500, 2200, 3000);
        ap_estimate_ppm(&s, 5000, 2000, 10000, 10000);
        assert(!s.ppm_valid && s.ppm == 0);
        json = ap_state_json(&s, "2026-10-27T00:00:00Z");
        quality = cJSON_GetObjectItemCaseSensitive(json, "airQuality");
        assert(cJSON_IsNull(cJSON_GetObjectItemCaseSensitive(quality, "ppm")));
        assert(cJSON_IsFalse(cJSON_GetObjectItemCaseSensitive(quality, "ppmValid")));
        cJSON_Delete(json);
    }
    ap_sample(&s, true, 1200, 1250, 1000000, 180, 1500, 2200, 3000);
    ap_estimate_ppm(&s, 5000, 2000, 10000, 10000);
    assert(!s.ppm_valid); /* Warm-up. */
    ap_sample(&s, false, 1200, 1250, 200000000, 180, 1500, 2200, 3000);
    ap_estimate_ppm(&s, 5000, 2000, 10000, 10000);
    assert(!s.ppm_valid); /* Read failure. */
    ap_sample(&s, true, 433, 437, 200000000, 180, 1500, 2200, 3000);
    ap_estimate_ppm(&s, 5000, 1000, 10000, 10000);
    assert(s.ppm_valid && s.ppm > 0 && s.ppm < 1); /* No fabricated 400 ppm floor. */
    const int invalid_config[][4] = {{0,1000,10000,10000}, {5000,0,10000,10000},
        {5000,1000,0,10000}, {5000,1000,10000,0}};
    for (unsigned i=0; i<sizeof(invalid_config)/sizeof(invalid_config[0]); ++i) {
        ap_estimate_ppm(&s, invalid_config[i][0], invalid_config[i][1],
            invalid_config[i][2], invalid_config[i][3]);
        assert(!s.ppm_valid);
    }
}

int main(void)
{
    test_ppm();
    ap_state_t s;
    ap_init(&s);
    assert(!s.power && s.mode == AP_MANUAL && s.warming_up);
    cJSON *initial = ap_state_json(&s, "2026-10-27T00:00:00Z");
    cJSON *initial_air = cJSON_GetObjectItemCaseSensitive(initial, "airQuality");
    assert(cJSON_IsNull(cJSON_GetObjectItemCaseSensitive(initial_air, "level")));
    assert(cJSON_IsNull(cJSON_GetObjectItemCaseSensitive(initial_air, "ppm")));
    cJSON_Delete(initial);
    ap_command_t on = parse("{\"commandId\":\"on-1\",\"issuedAt\":\"2026-10-27T00:00:00Z\",\"deviceId\":\"air-01\",\"type\":\"on\"}", NULL);
    ap_command_t off = parse("{\"commandId\":\"off-1\",\"issuedAt\":\"2026-10-27T00:00:00Z\",\"deviceId\":\"air-01\",\"type\":\"off\"}", NULL);
    ap_command_t automatic = parse("{\"commandId\":\"auto-1\",\"issuedAt\":\"2026-10-27T00:00:00Z\",\"deviceId\":\"air-01\",\"type\":\"set_mode\",\"mode\":\"auto\"}", NULL);
    assert(!ap_apply(&s, &on) && s.power && s.mode == AP_MANUAL);
    ap_sample(&s, true, 2500, 1800, 1000000, 180, 1500, 2200, 3000);
    assert(s.quality == AP_UNKNOWN);
    assert(!ap_apply(&s, &automatic) && !s.power && s.mode == AP_AUTO);
    cJSON *warming = ap_state_json(&s, "2026-10-27T00:00:00Z");
    cJSON *warming_air = cJSON_GetObjectItemCaseSensitive(warming, "airQuality");
    assert(cJSON_IsNull(cJSON_GetObjectItemCaseSensitive(warming_air, "level")));
    assert(cJSON_IsFalse(cJSON_GetObjectItemCaseSensitive(warming_air, "valid")));
    cJSON_Delete(warming);
    ap_sample(&s, true, 2200, 1600, 180000000, 180, 1500, 2200, 3000);
    assert(s.quality == AP_BAD && ap_automatic(&s) && s.power);
    assert(!strcmp(s.publisher, "system") && !s.command_id[0]);
    ap_sample(&s, true, 1800, 1300, 181000000, 180, 1500, 2200, 3000);
    assert(s.quality == AP_NORMAL && !ap_automatic(&s) && s.power);
    ap_sample(&s, true, 1500, 1100, 182000000, 180, 1500, 2200, 3000);
    assert(s.quality == AP_GOOD && ap_automatic(&s) && !s.power);
    ap_sample(&s, true, 1800, 1300, 183000000, 180, 1500, 2200, 3000);
    assert(!ap_automatic(&s) && !s.power);
    ap_sample(&s, true, 2400, 1700, 184000000, 180, 1500, 2200, 3000);
    assert(ap_automatic(&s) && s.power);
    assert(!ap_apply(&s, &off) && !s.power && s.mode == AP_MANUAL);
    assert(!ap_automatic(&s) && !s.power); /* Server OFF must stay OFF in bad air. */
    assert(!strcmp(s.publisher, "api") && !strcmp(s.command_id, "off-1"));
    assert(!ap_apply(&s, &automatic) && s.power);
    ap_sample(&s, false, 2400, 1700, 185000000, 180, 1500, 2200, 3000);
    assert(!s.sensor_valid && s.quality == AP_UNKNOWN && s.raw == -1 && s.adc_mv == -1);
    assert(ap_automatic(&s) && !s.power); /* Automatic control cannot use stale data. */
    assert(!ap_apply(&s, &on) && s.power && !ap_automatic(&s)); /* Manual stays usable. */
    ap_sample(&s, true, 4095, 3300, 186000000, 180, 1500, 2200, 3000);
    assert(!s.sensor_valid);
    ap_sample(&s, true, 0, 0, 187000000, 180, 1500, 2200, 3000);
    assert(!s.sensor_valid);
    /* Verify all grade boundaries and very_bad automatic activation. */
    const int raw_values[] = {1,1500,1501,2199,2200,2999,3000,4094};
    const ap_quality_t grades[] = {AP_GOOD,AP_GOOD,AP_NORMAL,AP_NORMAL,AP_BAD,AP_BAD,AP_VERY_BAD,AP_VERY_BAD};
    for (unsigned i=0;i<sizeof(raw_values)/sizeof(raw_values[0]);++i) {
        ap_sample(&s, true, raw_values[i], 1800, 200000000, 180, 1500, 2200, 3000);
        assert(s.quality == grades[i]);
    }
    assert(!ap_apply(&s, &off) && !s.power);
    assert(!ap_apply(&s, &automatic) && s.power);
    ap_sample(&s, true, 1500, 1100, 201000000, 180, 1500, 2200, 3000);
    assert(ap_automatic(&s) && !s.power);
    ap_sample(&s, true, 3000, 2200, 202000000, 180, 1500, 2200, 3000);
    assert(ap_automatic(&s) && s.power && !strcmp(s.publisher, "system"));
    cJSON *very_bad = ap_state_json(&s, "2026-10-27T00:00:00Z");
    cJSON *very_bad_air = cJSON_GetObjectItemCaseSensitive(very_bad, "airQuality");
    assert(!strcmp(cJSON_GetObjectItemCaseSensitive(very_bad_air, "level")->valuestring, "very_bad"));
    assert(cJSON_IsNull(cJSON_GetObjectItemCaseSensitive(very_bad_air, "ppm")));
    cJSON_Delete(very_bad);
    ap_sample(&s, false, 0, -1, 203000000, 180, 1500, 2200, 3000);
    cJSON *root = ap_state_json(&s, "2026-10-27T00:00:00Z");
    assert(root);
    cJSON *air = cJSON_GetObjectItemCaseSensitive(root, "airQuality");
    assert(cJSON_IsNull(cJSON_GetObjectItemCaseSensitive(air, "raw")));
    assert(cJSON_IsFalse(cJSON_GetObjectItemCaseSensitive(air, "valid")));
    assert(!cJSON_GetObjectItemCaseSensitive(air, "pm25"));
    assert(!cJSON_GetObjectItemCaseSensitive(air, "pm10"));
    assert(!cJSON_GetObjectItemCaseSensitive(air, "co2"));
    cJSON_Delete(root);
    root = ap_ack_json(on.id, "applied", NULL, &s, "2026-10-27T00:00:00Z");
    assert(root && cJSON_IsObject(cJSON_GetObjectItemCaseSensitive(root, "state")));
    assert(!strcmp(cJSON_GetObjectItemCaseSensitive(root, "commandId")->valuestring, on.id));
    cJSON_Delete(root);
    parse("{\"commandId\":\"\"}", "invalid_command_id");
    parse("{\"commandId\":\"x\",\"deviceId\":\"light-01\"}", "device_id_mismatch");
    parse("{\"commandId\":\"x\",\"deviceId\":\"air-01\"}", "missing_issued_at");
    parse("{\"commandId\":\"x\",\"deviceId\":\"air-01\",\"issuedAt\":\"t\",\"type\":\"set_mode\",\"mode\":\"turbo\"}", "invalid_mode");
    parse("{\"commandId\":\"x\",\"deviceId\":\"air-01\",\"issuedAt\":\"t\",\"type\":\"set_speed\"}", "invalid_type");
    parse("{\"commandId\":\"x\"}garbage", "invalid_json");
    ap_command_t invalid;
    assert(ap_parse("{}\0{}", 5, &invalid));
    assert(ap_parse(NULL, 1, &invalid));
    char too_large[AP_MAX_PAYLOAD+1]; memset(too_large, ' ', sizeof(too_large));
    assert(ap_parse(too_large, sizeof(too_large), &invalid));
    char timestamp[32]; assert(!ap_timestamp(0, timestamp));
    assert(ap_timestamp(1793059200, timestamp) && strchr(timestamp, 'Z'));
    puts("PASS: ppm curve/divider/invalid inputs, four grades, relay commands, warm-up, hysteresis, manual OFF, sensor faults, JSON and ACK schema");
}
