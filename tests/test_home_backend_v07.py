"""Offline checks against a pinned team backend, never a running board/API."""
import ast
from datetime import datetime, timezone
import os
import subprocess
import sys
from types import ModuleType, SimpleNamespace
from typing import Optional

import pytest

from tests.test_home_automation import home, owned_on, devices, rows, qualify_away, BASE
from src.integration.schemas import iso_time

COMMIT = "fb22929879d255f6c1788f465df48c941b9338b7"


@pytest.fixture
def backend_sources():
    checkout = os.environ.get("HOMEVIS_BACKEND_CHECKOUT")
    if not checkout:
        pytest.skip("optional HOMEVIS_BACKEND_CHECKOUT for real v0.7 contract checks")
    pytest.importorskip("pydantic")
    def read(path):
        return subprocess.run(["git", "show", f"{COMMIT}:{path}"], cwd=checkout, capture_output=True,
                              encoding="utf-8", check=True).stdout
    schema = ModuleType("homevis_home_v07_schema")
    sys.modules[schema.__name__] = schema
    exec(compile(read("app/schemas.py"), "backend-v0.7-schemas", "exec"), schema.__dict__)
    yield schema, read
    sys.modules.pop(schema.__name__, None)


@pytest.mark.parametrize("scenario", ["cooking_air_clean", "away_all_off", "voice_stove", "voice_air"])
def test_new_payloads_validate_with_backend_model(home, backend_sources, scenario):
    schema, _ = backend_sources
    env = home(whole_home_presence_verified=True)
    if scenario == "cooking_air_clean":
        owned_on(env)
        payload = rows(env)[0]["payload"]
    elif scenario == "away_all_off":
        qualify_away(env)
        payload = rows(env, scenario)[0]["payload"]
    else:
        action = ({"device": "stove", "deviceId": "induction-01", "action": "turn_on", "level": 3}
                  if scenario == "voice_stove" else {"device": "air_purifier", "deviceId": "air-01", "action": "set_mode", "mode": "auto"})
        payload = {"decisionId": "test", "voiceId": "v1", "scenario": "voice_command", "confidence": .9,
                   "timestamp": iso_time(BASE), "announcement": "확인해 주세요", "requiresConfirmation": True, "actions": [action]}
    schema.AiDecisionRequest.model_validate(payload)


def test_actual_ai_get_strips_control_provenance_and_off_stays_blocked(home, backend_sources):
    schema, read = backend_sources
    env = home()
    control = owned_on(env)
    state = {"reportedAt": iso_time(BASE + 1), "power": "on", "mode": "auto",
             "airQuality": {"level": "normal", "pm25": 10, "pm10": 20}, "lastControl": control}
    store = SimpleNamespace(get_device_state=lambda _: state, get_command=lambda _: SimpleNamespace(actor="ai"),
                            is_device_online=lambda _: True, get_device_last_seen=lambda _: datetime.fromtimestamp(BASE + 1, timezone.utc))
    registry = SimpleNamespace(STOVE="stove", WATER_PURIFIER="water_purifier", LIGHT="light", Device=SimpleNamespace)
    namespace = {"Optional": Optional, "LastControl": schema.LastControl, "datetime": datetime,
                 "DeviceInfo": schema.DeviceInfo, "state_store": store, "device_registry": registry}
    tree = ast.parse(read("app/ai_service.py"))
    functions = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in
                 {"_control_state", "_iso", "get_device_info"}]
    exec(compile(ast.Module(body=functions, type_ignores=[]), "actual-backend-device-info", "exec"), namespace)
    info = namespace["get_device_info"](SimpleNamespace(type="air_purifier", deviceId="air-01", room="room")).model_dump()
    assert info["control_state"] == "homevis" and "lastControl" not in info["current_state"]
    for second in range(1, 33):
        def inject(snapshot):
            info["updatedAt"] = info["current_state"]["reportedAt"] = iso_time(BASE + second)
            snapshot["items"][-1] = info.copy()
        devices(env, second, stove=False, air=True, mutate=inject)
    assert len(rows(env)) == 1
    # No explicit hold/away/priority field exists in the actual device command schema.
    assert not {"priority", "awayMode", "holdUntil", "source"} & schema.HomeDeviceCommandOut.model_fields.keys()
