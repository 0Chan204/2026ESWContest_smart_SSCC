"""Validate real firmware state/ACK JSON against the monorepo Backend schemas.

Run with ESP-IDF activated, using a Python environment with Pydantic v2:
    python tests/check_backend.py [path/to/backend]
"""
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import tempfile

project = Path(__file__).resolve().parents[1]
backend = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else project.parents[2] / "backend"
sys.path.insert(0, str(backend))
from app.schemas import AirPurifierState, HomeDeviceAck, HomeDeviceCommandOut

source = r'''
#include "air_model.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
static void emit(cJSON *value) {
    if (!value) exit(2);
    char *json = cJSON_PrintUnformatted(value);
    if (!json) exit(3);
    puts(json); cJSON_free(json); cJSON_Delete(value);
}
int main(void) {
    ap_state_t s;
    ap_init(&s);
    const int raw[] = {1000,1800,2500,3500,2500,0};
    const char *at = "2026-10-27T00:00:00Z";
    for (unsigned i=0;i<6;i++) {
        ap_sample(&s, i!=5, raw[i], 1700, i==4 ? 1000000 : 200000000, 180,1500,2200,3000);
        ap_estimate_ppm(&s, 5000, 1000, 10000, 10000);
        emit(ap_state_json(&s,at));
        emit(ap_ack_json("contract-1","applied",NULL,&s,at));
    }
    char input[AP_MAX_PAYLOAD+1];
    while (fgets(input,sizeof(input),stdin)) {
        ap_command_t cmd;
        const char *error=ap_parse(input,strlen(input),&cmd);
        if (!error) error=ap_apply(&s,&cmd);
        if (error) { fprintf(stderr,"%s\n",error); return 4; }
        emit(ap_ack_json(cmd.id,"applied",NULL,&s,at));
    }
    return 0;
}
'''
commands = [
    HomeDeviceCommandOut(commandId="on", issuedAt="2026-10-27T00:00:00Z", deviceId="air-01", type="on"),
    HomeDeviceCommandOut(commandId="off", issuedAt="2026-10-27T00:00:00Z", deviceId="air-01", type="off"),
    HomeDeviceCommandOut(commandId="auto", issuedAt="2026-10-27T00:00:00Z", deviceId="air-01", type="set_mode", mode="auto"),
    HomeDeviceCommandOut(commandId="manual", issuedAt="2026-10-27T00:00:00Z", deviceId="air-01", type="set_mode", mode="manual"),
]
cjson = Path(os.environ["IDF_PATH"]) / "components/json/cJSON"
with tempfile.TemporaryDirectory(prefix="homevis-air-contract-") as temp:
    temp = Path(temp)
    (temp / "check.c").write_text(source)
    subprocess.run([
        os.environ.get("CC", "cc"), "-std=c11", "-D_POSIX_C_SOURCE=200809L", "-Wall", "-Wextra", "-Werror",
        "-I", str(project / "main"), "-I", str(cjson), str(temp / "check.c"),
        str(project / "main/air_model.c"), str(cjson / "cJSON.c"), "-lm", "-o", str(temp / "check"),
    ], check=True)
    result = subprocess.run([str(temp / "check")], input="\n".join(c.model_dump_json(exclude_none=True) for c in commands)+"\n",
                            capture_output=True, text=True, check=True)
    payloads = [json.loads(line) for line in result.stdout.splitlines()]

levels = ["good", "normal", "bad", "very_bad", None, None]
assert len(payloads) == 16
for i, level in enumerate(levels):
    state = AirPurifierState.model_validate(payloads[2*i])
    ack = HomeDeviceAck.model_validate(payloads[2*i+1])
    ack_state = AirPurifierState.model_validate(ack.state)
    assert state.airQuality.level == level
    if i < 4:
        assert math.isclose(state.airQuality.ppm, 116.6020682 * ((5000-1700)/1700)**-2.769034857)
    else:
        assert state.airQuality.ppm is None
    assert state.airQuality.model_dump()["ppmValid"] == (i < 4)
    assert state.airQuality.model_dump()["ppmEstimated"] is True
    assert state.airQuality.model_dump()["ppmType"] == "co2_equivalent"
    assert state.airQuality.model_dump()["valid"] == (i < 4)
    assert state.airQuality.model_dump()["levelBasis"] == "adc_raw"
    assert ack_state == state
for cmd, payload in zip(commands, payloads[12:]):
    ack = HomeDeviceAck.model_validate(payload)
    state = AirPurifierState.model_validate(ack.state)
    assert ack.commandId == cmd.commandId and ack.result == "applied"
    assert state.lastControl.publisher == "api"
    if cmd.type == "on": assert state.power == "on" and state.mode == "manual"
    if cmd.type == "off": assert state.power == "off" and state.mode == "manual"
    if cmd.type == "set_mode": assert state.mode == cmd.mode
print("PASS: actual Backend schemas accept estimated ppm, four grades, warm-up/error nulls and ACKs; firmware accepts Backend commands")
