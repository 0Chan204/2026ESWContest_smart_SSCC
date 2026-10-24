"""
주요 API 흐름을 검증하는 테스트입니다. (CI에서 PR마다 자동 실행)

실행: pytest
"""

import time

from app import state_store
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


def _save_telemetry(device_state: str, level: int, temperature: float) -> None:
    state_store.save_telemetry(
        DEVICE,
        TelemetryReport(
            reportedAt="2026-10-02T12:00:00+00:00",
            burners=[
                BurnerTelemetry(burnerId=BURNER, deviceState=device_state, level=level, temperature=temperature)
            ],
            lastControl=LastControl(publisher="user"),
            alarm="off",
        ),
    )


def _event_types(client) -> list[str]:
    return [e["type"] for e in client.get(f"{PREFIX}/safety-events").json()["items"]]


def _token_of(confirm_url: str) -> str:
    return confirm_url.split("token=")[1]


def _wait_for(predicate, timeout_sec: float = 4.0) -> bool:
    """타이머로 진행되는 단계(보호자 알림, 자동 신고)를 기다립니다."""
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.1)
    return predicate()


def _alert_guardian_at_once(client, auto_report_sec: int = 60) -> None:
    """사용자 응답 대기 없이 사용자·보호자에게 동시에 알리도록 정책을 바꿉니다."""
    client.put(f"{PREFIX}/policies/fall-safety", json={"userAlertWaitSec": 0, "autoReportSec": auto_report_sec})


def _types_sent(published: list[dict]) -> list[tuple[str, str]]:
    return [(c["deviceId"], c["type"]) for c in published]


# ---------------------------------------------------------------------------
# 기본
# ---------------------------------------------------------------------------

def test_health(client):
    assert client.get("/health").json() == {"status": "ok", "storage": "memory"}


def test_swagger_is_grouped_by_feature(client):
    spec = client.get("/openapi.json").json()
    tags = [t["name"] for t in spec["tags"]]
    assert tags == [
        "회원 정보",
        "낙상 사고 감지",
        "AI 중앙 제어",
        "음성 명령",
        "AI 재실 판단",
        "인덕션 제어",
        "전등·정수기·환풍기 제어",
        "대시보드 화면",
        "안전 이벤트",
    ]

    # 모든 엔드포인트가 위 섹션 중 정확히 하나에 속해야 한다 (/health 제외)
    for path, methods in spec["paths"].items():
        if path == "/health":
            continue
        for method, operation in methods.items():
            assert len(operation["tags"]) == 1, f"{method} {path}"
            assert operation["tags"][0] in tags, f"{method} {path}"


def test_snapshot_before_any_telemetry(client):
    body = client.get(f"{PREFIX}/snapshot").json()
    assert body["appliances"][0]["online"] is False
    assert body["rooms"][ROOM]["safetyPhase"] == "normal"


# ---------------------------------------------------------------------------
# 화구 제어 + 과열 안전 규칙
# ---------------------------------------------------------------------------

def test_burner_command_is_published(client, published):
    res = client.post(
        f"{PREFIX}/appliances/{DEVICE}/burners/{BURNER}/commands", json={"type": "set_level", "level": 5}
    )
    assert res.status_code == 202
    assert published[-1]["type"] == "set_level"
    assert published[-1]["level"] == 5
    assert client.get(f"{PREFIX}/commands/{res.json()['commandId']}").json()["status"] == "sent"


def test_overheated_blocks_turn_on_but_allows_turn_off(client, published):
    _save_telemetry("overheated", 0, 160.0)
    url = f"{PREFIX}/appliances/{DEVICE}/burners/{BURNER}/commands"

    blocked = client.post(url, json={"type": "turn_on"})
    assert blocked.status_code == 409
    assert blocked.json()["detail"]["code"] == "BURNER_OVERHEATED"
    assert published == []
    assert "command_blocked" in _event_types(client)

    assert client.post(url, json={"type": "turn_off"}).status_code == 202
    assert published[-1]["type"] == "turn_off"


# ---------------------------------------------------------------------------
# 재실 판단 (v0.3: 저장·전달만, 서버가 직접 제어하지 않음)
# ---------------------------------------------------------------------------

def _presence(absent_sec: int, present: bool = False, zone: str = "far") -> dict:
    return {
        "room": ROOM,
        "zone": zone,
        "present": present,
        "absentSec": absent_sec,
        "confidence": 0.9,
        "observedAt": "2026-10-02T12:00:00+00:00",
        "modelVersion": "test-model",
    }


def test_presence_is_stored_without_auto_control(client, published):
    # 예전에는 700초 부재면 서버가 화구를 껐지만, 이제 판단은 AI 중앙 판정 엔진이 한다
    res = client.post(f"{PREFIX}/presence", json=_presence(700))
    assert res.status_code == 202
    assert res.json()["safetyPhase"] == "normal"
    assert published == []
    assert _event_types(client) == []
    assert client.get(f"{PREFIX}/snapshot").json()["rooms"][ROOM]["presence"]["absentSec"] == 700


# ---------------------------------------------------------------------------
# 낙상 사고 안전 기능
# ---------------------------------------------------------------------------

def test_guardian_register_and_read(client):
    assert client.get(f"{PREFIX}/guardian").status_code == 404

    res = client.put(f"{PREFIX}/guardian", json={"name": "보호자", "phone": "01000000000"})
    assert res.status_code == 200
    # CI에는 SOLAPI_* 키가 없으므로 실제 발송은 되지 않는 것이 정상
    assert res.json()["verificationSent"] is False
    assert client.get(f"{PREFIX}/guardian").json()["phone"] == "01000000000"


def test_user_register_and_read(client):
    assert client.get(f"{PREFIX}/user").status_code == 404

    res = client.put(f"{PREFIX}/user", json={"name": "사용자", "phone": "010-1111-2222"})
    assert res.status_code == 200
    assert res.json()["verificationSent"] is False
    # 하이픈이 있어도 숫자만 남겨 저장한다
    assert client.get(f"{PREFIX}/user").json() == {"name": "사용자", "phone": "01011112222"}


def test_invalid_phone_is_rejected(client):
    assert client.put(f"{PREFIX}/user", json={"name": "사용자", "phone": "abc"}).status_code == 422
    assert client.put(f"{PREFIX}/guardian", json={"name": "보호자", "phone": "1234"}).status_code == 422


def test_fall_alerts_user_first_then_guardian(client, monkeypatch):
    """1차 사용자 문자 -> userAlertWaitSec 동안 응답이 없으면 2차 보호자 문자 -> 3차 자동 신고"""
    from app import sms_service

    sent: list[tuple[str, str]] = []
    monkeypatch.setattr(sms_service, "send_sms", lambda to, content: sent.append((to, content)) or True)

    client.put(f"{PREFIX}/user", json={"name": "김사용", "phone": "01011112222"})
    client.put(f"{PREFIX}/guardian", json={"name": "박보호", "phone": "01033334444"})
    client.put(f"{PREFIX}/policies/fall-safety", json={"userAlertWaitSec": 1, "autoReportSec": 1})
    sent.clear()  # 등록 확인 문자 2건은 제외

    accepted = client.post(f"{PREFIX}/safety/fall-events", json=FALL_REPORT).json()
    incident_id = accepted["incidentId"]
    assert (accepted["stage"], accepted["userNotified"], accepted["guardianNotified"]) == ("user", True, False)
    assert accepted["guardianAlertAt"] is not None

    # 1차: 사용자에게만
    assert [to for to, _ in sent] == ["01011112222"]
    assert "김사용님" in sent[0][1]
    assert accepted["confirmUrl"] in sent[0][1]

    # 2차: 응답이 없으면 보호자에게
    assert _wait_for(lambda: len(sent) == 2)
    assert sent[1][0] == "01033334444"
    assert "김사용님 댁" in sent[1][1]
    assert "본인이 응답하지 않아" in sent[1][1]
    assert accepted["confirmUrl"] in sent[1][1]

    # 3차: 보호자도 응답이 없으면 자동 신고
    assert _wait_for(lambda: client.get(f"{PREFIX}/fall-incidents/{incident_id}").json()["status"] == "auto_reported")
    incident = client.get(f"{PREFIX}/fall-incidents/{incident_id}").json()
    assert (incident["stage"], incident["userNotified"], incident["guardianNotified"]) == ("guardian", True, True)
    assert incident["guardianAlertedAt"] is not None
    assert _event_types(client) == ["fall_detected", "fall_escalated", "fall_auto_reported"]

    purposes = [item["purpose"] for item in client.get(f"{PREFIX}/sms-logs").json()["items"]]
    assert purposes[:2] == ["fall_alert", "fall_user_alert"]


def test_user_answer_stops_escalation(client, monkeypatch):
    """사용자가 '괜찮음'을 누르면 보호자 문자와 자동 신고로 넘어가지 않는다."""
    from app import sms_service

    sent: list[str] = []
    monkeypatch.setattr(sms_service, "send_sms", lambda to, content: sent.append(to) or True)
    client.put(f"{PREFIX}/user", json={"name": "김사용", "phone": "01011112222"})
    client.put(f"{PREFIX}/guardian", json={"name": "박보호", "phone": "01033334444"})
    client.put(f"{PREFIX}/policies/fall-safety", json={"userAlertWaitSec": 1, "autoReportSec": 1})
    sent.clear()

    accepted = client.post(f"{PREFIX}/safety/fall-events", json=FALL_REPORT).json()
    resolved = client.post(
        f"{PREFIX}/fall-incidents/{accepted['incidentId']}/resolve",
        params={"token": _token_of(accepted["confirmUrl"])},
    )
    assert resolved.json()["status"] == "resolved"

    time.sleep(2.5)  # 보호자 알림·자동 신고 기한이 모두 지나도
    assert sent == ["01011112222"]
    incident = client.get(f"{PREFIX}/fall-incidents/{accepted['incidentId']}").json()
    assert (incident["status"], incident["stage"], incident["guardianNotified"]) == ("resolved", "user", False)
    assert "fall_escalated" not in _event_types(client)


def test_user_sms_failure_still_waits_for_dashboard_answer(client, monkeypatch):
    """사용자 문자가 실패해도(대회장 인터넷 불안정 등) 대시보드로 응답할 수 있으니 1차 대기는 그대로 진행한다."""
    from app import sms_service

    sent: list[str] = []

    def fake_send(to, content):
        sent.append(to)
        return to != "01011112222"

    monkeypatch.setattr(sms_service, "send_sms", fake_send)
    client.put(f"{PREFIX}/user", json={"name": "김사용", "phone": "01011112222"})
    client.put(f"{PREFIX}/guardian", json={"name": "박보호", "phone": "01033334444"})
    sent.clear()

    accepted = client.post(f"{PREFIX}/safety/fall-events", json=FALL_REPORT).json()
    assert sent == ["01011112222"]
    assert (accepted["stage"], accepted["userNotified"], accepted["guardianNotified"]) == ("user", False, False)
    event = client.get(f"{PREFIX}/safety-events").json()["items"][0]
    assert event["action"].endswith("사용자 문자 발송 실패 (30초 안에 응답 없으면 보호자 알림)")


def test_zero_wait_alerts_user_and_guardian_together(client, monkeypatch):
    from app import sms_service

    sent: list[str] = []
    monkeypatch.setattr(sms_service, "send_sms", lambda to, content: sent.append(to) or True)
    client.put(f"{PREFIX}/user", json={"name": "김사용", "phone": "01011112222"})
    client.put(f"{PREFIX}/guardian", json={"name": "박보호", "phone": "01033334444"})
    _alert_guardian_at_once(client)
    sent.clear()

    accepted = client.post(f"{PREFIX}/safety/fall-events", json=FALL_REPORT).json()
    assert sent == ["01011112222", "01033334444"]
    assert (accepted["stage"], accepted["userNotified"], accepted["guardianNotified"]) == ("guardian", True, True)


def test_fall_policy_defaults_and_partial_update(client):
    assert client.get(f"{PREFIX}/policies/fall-safety").json() == {"userAlertWaitSec": 30, "autoReportSec": 60}
    # 예전처럼 autoReportSec만 보내도 된다 (userAlertWaitSec는 기본값)
    assert client.put(f"{PREFIX}/policies/fall-safety", json={"autoReportSec": 10}).json() == {
        "userAlertWaitSec": 30,
        "autoReportSec": 10,
    }
    assert client.put(f"{PREFIX}/policies/fall-safety", json={"userAlertWaitSec": -1, "autoReportSec": 10}).status_code == 422


def test_sms_request_format(monkeypatch):
    """솔라피로 나가는 요청의 주소, 인증 헤더, 본문 형식을 확인한다 (실제 발송은 하지 않음)."""
    import hashlib
    import hmac
    import re

    from app import sms_service

    monkeypatch.setattr(settings, "SOLAPI_API_KEY", "test-key", raising=False)
    monkeypatch.setattr(settings, "SOLAPI_API_SECRET", "test-secret", raising=False)
    monkeypatch.setattr(settings, "SOLAPI_SENDER_PHONE", "010-9999-8888", raising=False)

    captured = {}

    class FakeResponse:
        status_code = 200
        text = "{}"

    def fake_post(url, headers, json, timeout):
        captured.update(url=url, headers=headers, json=json)
        return FakeResponse()

    monkeypatch.setattr(sms_service.requests, "post", fake_post)

    assert sms_service.send_sms("010-1234-5678", "테스트") is True
    assert captured["url"] == "https://api.solapi.com/messages/v4/send"
    assert captured["json"] == {"message": {"to": "01012345678", "from": "01099998888", "text": "테스트"}}

    auth = captured["headers"]["Authorization"]
    m = re.fullmatch(r"HMAC-SHA256 apiKey=test-key, date=(\S+), salt=(\w+), signature=(\w+)", auth)
    assert m, auth
    date, salt, signature = m.groups()
    assert signature == hmac.new(b"test-secret", (date + salt).encode(), hashlib.sha256).hexdigest()


def test_sms_failure_returns_false(monkeypatch):
    from app import sms_service

    monkeypatch.setattr(settings, "SOLAPI_API_KEY", "k", raising=False)
    monkeypatch.setattr(settings, "SOLAPI_API_SECRET", "s", raising=False)
    monkeypatch.setattr(settings, "SOLAPI_SENDER_PHONE", "01099998888", raising=False)

    class FakeResponse:
        status_code = 403
        text = '{"errorCode":"Forbidden"}'

    monkeypatch.setattr(sms_service.requests, "post", lambda *a, **k: FakeResponse())
    assert sms_service.send_sms("01012345678", "테스트") is False


def test_fall_turns_off_burner_and_can_be_resolved(client, published):
    accepted = client.post(f"{PREFIX}/safety/fall-events", json=FALL_REPORT)
    assert accepted.status_code == 202
    incident_id = accepted.json()["incidentId"]
    token = _token_of(accepted.json()["confirmUrl"])

    # 재실 정책과 달리 단계 없이 즉시 전원 차단 + 전등 깜빡임
    assert _types_sent(published) == [(DEVICE, "turn_off"), ("light-01", "blink")]
    assert published[-1]["durationSec"] == settings.LIGHT_BLINK_SEC
    assert accepted.json()["lightBlinkSent"] is True
    assert client.get(f"{PREFIX}/fall-incidents/{incident_id}").json()["status"] == "pending"

    wrong = client.post(f"{PREFIX}/fall-incidents/{incident_id}/resolve", params={"token": "wrong"})
    assert wrong.status_code == 403

    resolved = client.post(f"{PREFIX}/fall-incidents/{incident_id}/resolve", params={"token": token})
    assert resolved.json()["status"] == "resolved"

    again = client.post(f"{PREFIX}/fall-incidents/{incident_id}/report", params={"token": token})
    assert again.status_code == 409
    assert _event_types(client) == ["fall_detected", "fall_resolved"]


def test_fall_can_be_reported(client):
    accepted = client.post(f"{PREFIX}/safety/fall-events", json=FALL_REPORT).json()
    res = client.post(
        f"{PREFIX}/fall-incidents/{accepted['incidentId']}/report",
        params={"token": _token_of(accepted["confirmUrl"])},
    )
    assert res.json()["status"] == "reported"


def test_fall_is_auto_reported_when_nobody_answers(client):
    _alert_guardian_at_once(client, auto_report_sec=1)
    accepted = client.post(f"{PREFIX}/safety/fall-events", json=FALL_REPORT).json()
    assert accepted["stage"] == "guardian"
    incident_id = accepted["incidentId"]

    assert _wait_for(lambda: client.get(f"{PREFIX}/fall-incidents/{incident_id}").json()["status"] == "auto_reported")
    assert "fall_auto_reported" in _event_types(client)


def test_unknown_fall_incident_is_404(client):
    assert client.get(f"{PREFIX}/fall-incidents/nope").status_code == 404
    assert client.post(f"{PREFIX}/fall-incidents/nope/resolve", params={"token": "x"}).status_code == 404


# ---------------------------------------------------------------------------
# 안전 이벤트 피드백 / 문자 발송 이력
# ---------------------------------------------------------------------------

def test_feedback_is_stored_on_event(client):
    client.post(f"{PREFIX}/safety/fall-events", json=FALL_REPORT)
    event_id = client.get(f"{PREFIX}/safety-events").json()["items"][0]["eventId"]
    assert client.get(f"{PREFIX}/safety-events/{event_id}").json()["feedback"] is None

    res = client.post(f"{PREFIX}/safety-events/{event_id}/feedback", json={"verdict": "rejected", "comment": "오탐"})
    assert res.status_code == 201

    feedback = client.get(f"{PREFIX}/safety-events/{event_id}").json()["feedback"]
    assert feedback["verdict"] == "rejected"
    assert feedback["comment"] == "오탐"
    assert feedback["submittedAt"] == res.json()["submittedAt"]

    # 다시 제출하면 최근 의견으로 바뀐다
    client.post(f"{PREFIX}/safety-events/{event_id}/feedback", json={"verdict": "approved"})
    assert client.get(f"{PREFIX}/safety-events/{event_id}").json()["feedback"]["verdict"] == "approved"

    assert client.post(f"{PREFIX}/safety-events/nope/feedback", json={"verdict": "approved"}).status_code == 404


def test_sms_logs_record_every_send(client, monkeypatch):
    from app import sms_service

    monkeypatch.setattr(sms_service, "send_sms", lambda to, content: to != "01011112222")

    client.put(f"{PREFIX}/user", json={"name": "김사용", "phone": "01011112222"})      # 실패하도록 설정
    client.put(f"{PREFIX}/guardian", json={"name": "박보호", "phone": "01033334444"})  # 성공
    _alert_guardian_at_once(client)
    incident_id = client.post(f"{PREFIX}/safety/fall-events", json=FALL_REPORT).json()["incidentId"]

    body = client.get(f"{PREFIX}/sms-logs").json()
    assert body["total"] == 4
    guardian_alert, user_alert, guardian_check, user_check = body["items"]  # 최신순

    # 대기 시간 0: 사용자(실패)와 보호자에게 동시에 보냄
    assert (guardian_alert["purpose"], guardian_alert["to"], guardian_alert["success"]) == ("fall_alert", "01033334444", True)
    assert guardian_alert["incidentId"] == incident_id
    assert (user_alert["purpose"], user_alert["to"], user_alert["success"]) == ("fall_user_alert", "01011112222", False)
    assert user_alert["incidentId"] == incident_id
    assert (guardian_check["purpose"], guardian_check["success"]) == ("guardian_verification", True)
    assert (user_check["purpose"], user_check["to"], user_check["success"]) == ("user_verification", "01011112222", False)

    # 본문(확인 링크의 토큰 포함)은 기록에 남기지 않는다
    assert all("content" not in item and "text" not in item for item in body["items"])
    assert len(client.get(f"{PREFIX}/sms-logs", params={"limit": 1}).json()["items"]) == 1


def test_bad_sms_setting_does_not_break_registration(client, monkeypatch):
    """문자 설정값이 잘못돼 요청을 만들 수 없어도, 연락처 등록은 정상 응답해야 한다."""
    monkeypatch.setattr(settings, "SOLAPI_API_KEY", "한글이섞인키", raising=False)
    monkeypatch.setattr(settings, "SOLAPI_API_SECRET", "secret", raising=False)
    monkeypatch.setattr(settings, "SOLAPI_SENDER_PHONE", "01099998888", raising=False)

    res = client.put(f"{PREFIX}/guardian", json={"name": "보호자", "phone": "01000000000"})
    assert res.status_code == 200
    assert res.json()["verificationSent"] is False
    assert client.get(f"{PREFIX}/sms-logs").json()["items"][0]["success"] is False


# ---------------------------------------------------------------------------
# 낙상 처리: 각 단계는 독립적으로 수행되어야 한다
# ---------------------------------------------------------------------------

def test_fall_without_any_contact_still_shuts_off(client, published):
    """사용자·보호자 연락처가 하나도 없어도 인덕션 차단과 알림은 그대로 진행된다."""
    res = client.post(f"{PREFIX}/safety/fall-events", json=FALL_REPORT)
    assert res.status_code == 202
    assert res.json()["shutoffSent"] is True
    assert res.json()["guardianNotified"] is False
    assert (DEVICE, "turn_off") in _types_sent(published)

    event = client.get(f"{PREFIX}/safety-events").json()["items"][0]
    assert event["type"] == "fall_detected"
    assert event["action"] == (
        "인덕션 비상 전원 차단 명령 전송 + 전등 깜빡임 명령 전송 + "
        "사용자 미등록으로 문자 미발송 (30초 안에 응답 없으면 보호자 알림)"
    )
    assert client.get(f"{PREFIX}/sms-logs").json()["total"] == 0


def test_fall_records_what_was_actually_done(client, published, monkeypatch):
    from app import sms_service

    monkeypatch.setattr(sms_service, "send_sms", lambda to, content: True)
    client.put(f"{PREFIX}/guardian", json={"name": "박보호", "phone": "01033334444"})
    _alert_guardian_at_once(client)

    accepted = client.post(f"{PREFIX}/safety/fall-events", json=FALL_REPORT).json()
    assert (accepted["shutoffSent"], accepted["guardianNotified"]) == (True, True)

    incident = client.get(f"{PREFIX}/fall-incidents/{accepted['incidentId']}").json()
    assert (incident["shutoffSent"], incident["guardianNotified"]) == (True, True)
    event = client.get(f"{PREFIX}/safety-events/{incident['eventId']}").json()
    assert event["action"] == "인덕션 비상 전원 차단 명령 전송 + 전등 깜빡임 명령 전송 + 사용자 미등록으로 문자 미발송 + 보호자 문자 발송"


def test_fall_still_notifies_when_induction_is_unreachable(client, monkeypatch):
    """인덕션 통신이 끊겨 차단 명령을 못 보내도, 대시보드 알림과 보호자 문자는 나가야 한다."""
    from app import mqtt_client, sms_service

    def broken_publish(device_id, payload):
        raise RuntimeError("Message publish failed: The client is not currently connected.")

    sent: list[tuple[str, str]] = []
    monkeypatch.setattr(mqtt_client, "publish_command", broken_publish)
    monkeypatch.setattr(sms_service, "send_sms", lambda to, content: sent.append((to, content)) or True)
    client.put(f"{PREFIX}/guardian", json={"name": "박보호", "phone": "01033334444"})
    _alert_guardian_at_once(client)
    sent.clear()

    res = client.post(f"{PREFIX}/safety/fall-events", json=FALL_REPORT)
    assert res.status_code == 202
    assert res.json()["shutoffSent"] is False
    assert res.json()["guardianNotified"] is True

    # 문자에는 인덕션이 꺼졌다고 쓰지 않고, 직접 확인해 달라고 안내한다
    assert [to for to, _ in sent] == ["01033334444"]
    assert "차단 명령을 보내지 못했으니" in sent[0][1]
    assert "자동 차단 명령을 보냈습니다" not in sent[0][1]

    event = client.get(f"{PREFIX}/safety-events").json()["items"][0]
    assert event["action"] == "인덕션 차단 명령 전송 실패 + 전등 깜빡임 명령 전송 + 사용자 미등록으로 문자 미발송 + 보호자 문자 발송"

    # 보호자는 여전히 링크로 사건을 처리할 수 있다
    token = _token_of(res.json()["confirmUrl"])
    resolved = client.post(f"{PREFIX}/fall-incidents/{res.json()['incidentId']}/resolve", params={"token": token})
    assert resolved.json()["status"] == "resolved"


def test_fall_reports_sms_failure(client, published, monkeypatch):
    from app import sms_service

    monkeypatch.setattr(sms_service, "send_sms", lambda to, content: False)
    client.put(f"{PREFIX}/guardian", json={"name": "박보호", "phone": "01033334444"})
    _alert_guardian_at_once(client)

    accepted = client.post(f"{PREFIX}/safety/fall-events", json=FALL_REPORT).json()
    assert (accepted["shutoffSent"], accepted["guardianNotified"]) == (True, False)
    event = client.get(f"{PREFIX}/safety-events").json()["items"][0]
    assert event["action"] == "인덕션 비상 전원 차단 명령 전송 + 전등 깜빡임 명령 전송 + 사용자 미등록으로 문자 미발송 + 보호자 문자 발송 실패"


def test_failed_publish_marks_command_failed(client, monkeypatch):
    from app import mqtt_client

    def broken_publish(device_id, payload):
        raise RuntimeError("not connected")

    monkeypatch.setattr(mqtt_client, "publish_command", broken_publish)
    client.post(f"{PREFIX}/safety/fall-events", json=FALL_REPORT)

    from app import state_store as store

    records = [r for r in store._commands.values() if r.deviceType == "stove"]
    assert len(records) == 1 and records[0].status == "failed"


def test_fall_light_failure_does_not_stop_the_rest(client, monkeypatch):
    """전등 통신이 끊겨도 인덕션 차단과 문자는 진행된다."""
    from app import mqtt_client, sms_service

    def broken(device_id, payload):
        raise RuntimeError("not connected")

    monkeypatch.setattr(mqtt_client, "publish_device_command", broken)
    monkeypatch.setattr(sms_service, "send_sms", lambda to, content: True)
    client.put(f"{PREFIX}/guardian", json={"name": "박보호", "phone": "01033334444"})
    _alert_guardian_at_once(client)

    accepted = client.post(f"{PREFIX}/safety/fall-events", json=FALL_REPORT).json()
    assert (accepted["shutoffSent"], accepted["lightBlinkSent"], accepted["guardianNotified"]) == (True, False, True)
    event = client.get(f"{PREFIX}/safety-events").json()["items"][0]
    assert event["action"] == "인덕션 비상 전원 차단 명령 전송 + 전등 깜빡임 명령 전송 실패 + 사용자 미등록으로 문자 미발송 + 보호자 문자 발송"


def test_fall_without_light_skips_blink(client, published, monkeypatch):
    monkeypatch.setattr(settings, "HOMEVIS_DEVICES", "[]", raising=False)
    accepted = client.post(f"{PREFIX}/safety/fall-events", json=FALL_REPORT).json()
    assert accepted["lightBlinkSent"] is False
    assert _types_sent(published) == [(DEVICE, "turn_off")]
    assert "등록된 전등 없음" in client.get(f"{PREFIX}/safety-events").json()["items"][0]["action"]
