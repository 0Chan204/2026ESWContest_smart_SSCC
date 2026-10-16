"""
pytest 공용 설정입니다.

CI 환경(GitHub Actions)에는 MQTT 브로커(Mosquitto)가 없으므로, 서버가 브로커에
연결/발행하는 부분만 가짜로 바꿔치기합니다. 그 외 로직(안전 규칙, 부재중 정책,
낙상 사건 처리 등)은 전부 실제 코드가 그대로 실행됩니다.
"""

import pytest
from fastapi.testclient import TestClient

from app import db, mqtt_client, state_store
from app.config import settings


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
    # v0.3: 전등·정수기 명령도 같은 리스트에 모읍니다 (payload 안에 deviceId가 들어 있음)
    monkeypatch.setattr(
        mqtt_client,
        "publish_device_command",
        lambda device_id, payload: commands.append({"deviceId": device_id, **payload}),
    )
    return commands


@pytest.fixture(autouse=True)
def reset_state(monkeypatch):
    """테스트끼리 영향을 주지 않도록 매번 메모리를 비우고, 실제 DB에는 절대 접속하지 않게 합니다.
    (개발자 PC의 .env에 MONGODB_URI가 있어도 테스트가 실제 DB를 건드리지 않도록)"""
    monkeypatch.setattr(settings, "MONGODB_URI", "", raising=False)
    # 테스트 중에는 실제 날씨 서버에 접속하지 않습니다 (필요한 테스트에서만 가짜 응답으로 켬)
    monkeypatch.setattr(settings, "WEATHER_ENABLED", False, raising=False)
    db.use_database(None)
    state_store.reset_memory()
    yield
    db.flush()
    db.use_database(None)


@pytest.fixture()
def mongo():
    """실제 MongoDB 대신 메모리에서 동작하는 가짜 DB(mongomock)를 연결합니다."""
    import mongomock

    database = mongomock.MongoClient()["homevis_test"]
    db.use_database(database)
    return database


@pytest.fixture()
def client(published):
    from app.main import app

    with TestClient(app) as test_client:
        yield test_client
