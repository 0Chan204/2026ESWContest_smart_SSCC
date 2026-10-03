"""
pytest 공용 설정입니다.

CI 환경(GitHub Actions)에는 MQTT 브로커(Mosquitto)가 없으므로, 서버가 브로커에
연결/발행하는 부분만 가짜로 바꿔치기합니다. 그 외 로직(안전 규칙, 부재중 정책,
낙상 사건 처리 등)은 전부 실제 코드가 그대로 실행됩니다.
"""

import pytest
from fastapi.testclient import TestClient

from app import mqtt_client, state_store
from app.config import settings
from app.schemas import FallPolicy, KitchenAbsencePolicy


@pytest.fixture()
def published(monkeypatch):
    """서버가 MQTT로 발행하려던 제어 명령을 가로채서 리스트로 모아줍니다."""
    commands: list[dict] = []
    monkeypatch.setattr(mqtt_client, "start", lambda: None)
    monkeypatch.setattr(mqtt_client, "stop", lambda: None)
    monkeypatch.setattr(
        mqtt_client,
        "publish_command",
        lambda device_id, payload: commands.append({"deviceId": device_id, **payload}),
    )
    return commands


@pytest.fixture(autouse=True)
def reset_state():
    """state_store는 모듈 전역 메모리라서, 테스트끼리 영향을 주지 않도록 매번 비웁니다."""
    for name in (
        "_latest_telemetry",
        "_last_seen_at",
        "_commands",
        "_device_command_ids",
        "_safety_events",
        "_sessions",
        "_active_session_by_device",
        "_presence_by_room",
        "_absence_stage_by_room",
        "_fall_incidents",
        "_fall_tokens",
    ):
        getattr(state_store, name).clear()
    state_store._safety_event_order.clear()
    state_store._guardian = None
    state_store._user = None
    state_store.set_policy(KitchenAbsencePolicy(**settings.DEFAULT_POLICY))
    state_store.set_fall_policy(FallPolicy(**settings.DEFAULT_FALL_POLICY))
    yield


@pytest.fixture()
def client(published):
    from app.main import app

    with TestClient(app) as test_client:
        yield test_client
