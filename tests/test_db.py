"""
MongoDB 저장/복원을 검증하는 테스트입니다.
실제 DB 대신 mongomock(메모리에서 동작하는 가짜 MongoDB)을 사용합니다.

핵심 시나리오: 데이터를 만든다 -> 서버를 껐다 켠다 -> 데이터가 그대로 남아 있다.
"""

import time
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from app import db, state_store
from app.config import settings
from app.schemas import BurnerTelemetry, LastControl, TelemetryReport

PREFIX = settings.API_PREFIX
DEVICE = settings.INDUCTION_DEVICE_ID
BURNER = settings.BURNER_ID
ROOM = settings.KITCHEN_ROOM

FALL_REPORT = {
    "room": ROOM,
    "confidence": 0.95,
    "observedAt": "2026-10-02T12:00:00+00:00",
    "modelVersion": "test-model",
}


def _restart_server():
    """서버 재시작을 흉내 냅니다: 메모리를 전부 비우고 앱을 새로 시작(DB에서 다시 불러옴)."""
    from app.main import app

    db.flush()
    state_store.reset_memory()
    return TestClient(app)


def test_health_reports_mongodb(mongo, client):
    assert client.get("/health").json() == {"status": "ok", "storage": "mongodb"}


def test_everything_survives_restart(mongo, published):
    from app.main import app

    with TestClient(app) as client:
        client.put(f"{PREFIX}/user", json={"name": "김사용", "phone": "010-1111-2222"})
        client.put(f"{PREFIX}/guardian", json={"name": "박보호", "phone": "01033334444"})
        client.put(f"{PREFIX}/policies/fall-safety", json={"userAlertWaitSec": 120, "autoReportSec": 300})

        policy = client.get(f"{PREFIX}/policies/kitchen-absence").json()
        policy["offAfterSec"] = 999
        client.put(f"{PREFIX}/policies/kitchen-absence", json=policy)

        command_id = client.post(
            f"{PREFIX}/appliances/{DEVICE}/burners/{BURNER}/commands", json={"type": "set_level", "level": 3}
        ).json()["commandId"]

        state_store.save_telemetry(
            DEVICE,
            TelemetryReport(
                reportedAt="2026-10-02T12:00:00+00:00",
                burners=[BurnerTelemetry(burnerId=BURNER, deviceState="on", level=3, temperature=80.0)],
                lastControl=LastControl(publisher="api", commandId=command_id),
                alarm="off",
            ),
        )

        presence = {
            "room": ROOM, "zone": "far", "present": False, "absentSec": 200,
            "confidence": 0.9, "observedAt": "2026-10-02T12:00:00+00:00", "modelVersion": "m",
        }
        client.post(f"{PREFIX}/presence", json=presence)  # 저장만 됨 (v0.3: 서버가 직접 제어하지 않음)
        client.post(
            f"{PREFIX}/ai/decisions",
            json={
                "decisionId": "d-restart",
                "scenario": "bedtime_light_off",
                "confidence": 0.9,
                "timestamp": "2026-10-02T12:00:00+00:00",
                "actions": [{"device": "light", "action": "off"}],
            },
        )  # -> ai_control

        accepted = client.post(f"{PREFIX}/safety/fall-events", json=FALL_REPORT).json()
        incident_id = accepted["incidentId"]
        token = accepted["confirmUrl"].split("token=")[1]

        first_event_id = client.get(f"{PREFIX}/safety-events").json()["items"][0]["eventId"]
        client.post(f"{PREFIX}/safety-events/{first_event_id}/feedback", json={"verdict": "rejected", "comment": "오탐"})

        events_before = client.get(f"{PREFIX}/safety-events").json()["items"]
        sms_logs_before = client.get(f"{PREFIX}/sms-logs").json()

    with _restart_server() as client:
        assert client.get(f"{PREFIX}/user").json() == {"name": "김사용", "phone": "01011112222"}
        assert client.get(f"{PREFIX}/guardian").json() == {"name": "박보호", "phone": "01033334444"}
        assert client.get(f"{PREFIX}/policies/fall-safety").json() == {"userAlertWaitSec": 120, "autoReportSec": 300}
        assert client.get(f"{PREFIX}/policies/kitchen-absence").json()["offAfterSec"] == 999

        assert client.get(f"{PREFIX}/commands/{command_id}").json()["status"] == "sent"
        assert client.get(f"{PREFIX}/devices/{DEVICE}/telemetry").json()["burners"][0]["temperature"] == 80.0

        # 안전 이벤트는 내용과 순서가 모두 그대로여야 한다
        assert client.get(f"{PREFIX}/safety-events").json()["items"] == events_before
        assert [e["type"] for e in events_before] == ["ai_control", "fall_detected"]
        assert events_before[0]["feedback"]["comment"] == "오탐"

        # 문자 발송 이력도 유지 (사용자 확인, 보호자 확인, 낙상 알림)
        assert client.get(f"{PREFIX}/sms-logs").json() == sms_logs_before
        assert sms_logs_before["total"] == 3

        # 재실 판단 결과도 유지
        assert client.get(f"{PREFIX}/snapshot").json()["rooms"][ROOM]["presence"]["absentSec"] == 200

        # 낙상 사건과 확인 토큰도 유지: 재시작 후에도 보호자가 링크로 처리할 수 있다
        assert client.get(f"{PREFIX}/fall-incidents/{incident_id}").json()["status"] == "pending"
        res = client.post(f"{PREFIX}/fall-incidents/{incident_id}/resolve", params={"token": token})
        assert res.json()["status"] == "resolved"

    with _restart_server() as client:
        assert client.get(f"{PREFIX}/fall-incidents/{incident_id}").json()["status"] == "resolved"
        types = [e["type"] for e in client.get(f"{PREFIX}/safety-events").json()["items"]]
        assert types == ["ai_control", "fall_detected", "fall_resolved"]


def test_overdue_fall_incident_is_auto_reported_after_restart(mongo, published):
    """서버가 꺼져 있는 동안 자동 신고 기한이 지난 사건은, 다시 켜지면 곧바로 자동 신고된다."""
    from app.main import app

    with TestClient(app) as client:
        incident_id = client.post(f"{PREFIX}/safety/fall-events", json=FALL_REPORT).json()["incidentId"]
        overdue = (datetime.now(timezone.utc) - timedelta(seconds=5)).isoformat(timespec="seconds")
        # 사용자 응답 기한과 자동 신고 기한이 모두 지난 상태로 만든다
        state_store.update_fall_incident(incident_id, guardianAlertAt=overdue, autoReportAt=overdue)

    with _restart_server() as client:
        status = "pending"
        for _ in range(40):
            status = client.get(f"{PREFIX}/fall-incidents/{incident_id}").json()["status"]
            if status != "pending":
                break
            time.sleep(0.1)
        assert status == "auto_reported"


def test_user_stage_incident_moves_to_guardian_after_restart(mongo, published, monkeypatch):
    """사용자 응답을 기다리던 중 서버가 꺼졌다 켜져도, 기한이 지났으면 보호자에게 넘어간다."""
    from app import sms_service
    from app.main import app

    sent: list[str] = []
    monkeypatch.setattr(sms_service, "send_sms", lambda to, content: sent.append(to) or True)

    with TestClient(app) as client:
        client.put(f"{PREFIX}/user", json={"name": "김사용", "phone": "01011112222"})
        client.put(f"{PREFIX}/guardian", json={"name": "박보호", "phone": "01033334444"})
        incident_id = client.post(f"{PREFIX}/safety/fall-events", json=FALL_REPORT).json()["incidentId"]
        assert client.get(f"{PREFIX}/fall-incidents/{incident_id}").json()["stage"] == "user"
        overdue = (datetime.now(timezone.utc) - timedelta(seconds=5)).isoformat(timespec="seconds")
        later = (datetime.now(timezone.utc) + timedelta(seconds=60)).isoformat(timespec="seconds")
        state_store.update_fall_incident(incident_id, guardianAlertAt=overdue, autoReportAt=later)

    with _restart_server() as client:
        stage = "user"
        for _ in range(40):
            stage = client.get(f"{PREFIX}/fall-incidents/{incident_id}").json()["stage"]
            if stage != "user":
                break
            time.sleep(0.1)
        incident = client.get(f"{PREFIX}/fall-incidents/{incident_id}").json()
        assert (incident["stage"], incident["status"], incident["guardianNotified"]) == ("guardian", "pending", True)
        assert sent[-1] == "01033334444"


def test_telemetry_is_logged_with_expiry_index(mongo):
    for temperature in (30.0, 40.0):
        state_store.save_telemetry(
            DEVICE,
            TelemetryReport(
                reportedAt="2026-10-02T12:00:00+00:00",
                burners=[BurnerTelemetry(burnerId=BURNER, deviceState="on", level=1, temperature=temperature)],
                lastControl=LastControl(publisher="user"),
                alarm="off",
            ),
        )
    db.flush()

    assert mongo[db.TELEMETRY_LOGS].count_documents({"deviceId": DEVICE}) == 2
    assert mongo[db.TELEMETRY_LATEST].find_one({"_id": DEVICE})["report"]["burners"][0]["temperature"] == 40.0

    indexes = mongo[db.TELEMETRY_LOGS].index_information()
    ttl = [i for i in indexes.values() if "expireAfterSeconds" in i]
    assert ttl and ttl[0]["expireAfterSeconds"] == settings.TELEMETRY_LOG_TTL_DAYS * 24 * 3600


def test_runs_in_memory_when_db_is_unreachable(monkeypatch, published):
    """접속 주소가 틀려도 서버는 죽지 않고 메모리로 동작해야 한다."""
    from app.main import app

    monkeypatch.setattr(settings, "MONGODB_URI", "mongodb://127.0.0.1:1/?serverSelectionTimeoutMS=200")
    with TestClient(app) as client:
        assert client.get("/health").json()["storage"] == "memory"
        assert client.put(f"{PREFIX}/guardian", json={"name": "보호자", "phone": "01000000000"}).status_code == 200


def test_ai_decisions_and_device_states_survive_restart(mongo, published):
    """v0.3: AI 판단 기록, 전등 상태, 복구용 화력이 재시작 후에도 남아 있는지"""
    from app import home_device_service
    from app.main import app

    with TestClient(app) as client:
        state_store.save_telemetry(
            DEVICE,
            TelemetryReport(
                reportedAt="2026-10-16T12:00:00+00:00",
                burners=[BurnerTelemetry(burnerId=BURNER, deviceState="on", level=7, temperature=100.0)],
                lastControl=LastControl(publisher="user"),
                alarm="off",
            ),
        )
        client.post(
            f"{PREFIX}/ai/decisions",
            json={
                "decisionId": "d-persist",
                "scenario": "stove_absence",
                "confidence": 0.8,
                "timestamp": "2026-10-16T12:00:00+00:00",
                "actions": [{"device": "stove", "action": "turn_off"}],
            },
        )
        home_device_service.handle_state(
            "light-01", "light", {"reportedAt": "2026-10-16T12:00:00+00:00", "power": "on"}
        )

    with _restart_server() as client:
        assert client.get(f"{PREFIX}/ai/decisions/d-persist").json()["actions"][0]["status"] == "sent"
        assert client.get(f"{PREFIX}/devices/light-01").json()["current_state"]["power"] == "on"
        assert state_store.get_restore_level(DEVICE) == 7
