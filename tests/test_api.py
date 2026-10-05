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


# ---------------------------------------------------------------------------
# 기본
# ---------------------------------------------------------------------------

def test_health(client):
    assert client.get("/health").json() == {"status": "ok", "storage": "memory"}


def test_swagger_is_grouped_by_feature(client):
    spec = client.get("/openapi.json").json()
    tags = [t["name"] for t in spec["tags"]]
    assert tags == ["회원 정보", "낙상 사고 감지", "AI 재실 판단", "인덕션 제어", "대시보드 화면", "안전 이벤트"]

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
# 부재중 자동 제어 정책
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


def test_absence_reduces_then_turns_off_then_user_returns(client, published):
    res = client.post(f"{PREFIX}/presence", json=_presence(200))
    assert res.json()["safetyPhase"] == "auto_reduced"
    assert published[-1]["type"] == "set_level"

    res = client.post(f"{PREFIX}/presence", json=_presence(700))
    assert res.json()["safetyPhase"] == "auto_off"
    assert published[-1]["type"] == "turn_off"

    res = client.post(f"{PREFIX}/presence", json=_presence(0, present=True, zone="kitchen"))
    assert res.json()["safetyPhase"] == "normal"
    assert _event_types(client) == ["auto_power_reduced", "auto_power_off", "user_returned"]


def test_near_zone_waits_longer(client, published):
    # near 구역은 임계값이 2배(180초 -> 360초)라서 200초로는 저감되지 않고 관찰만 한다
    res = client.post(f"{PREFIX}/presence", json=_presence(200, zone="near"))
    assert res.json()["safetyPhase"] == "absence_watch"
    assert published == []


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


def test_fall_sms_goes_only_to_guardian(client, monkeypatch):
    from app import sms_service

    sent: list[tuple[str, str]] = []
    monkeypatch.setattr(sms_service, "send_sms", lambda to, content: sent.append((to, content)) or True)

    client.put(f"{PREFIX}/user", json={"name": "김사용", "phone": "01011112222"})
    client.put(f"{PREFIX}/guardian", json={"name": "박보호", "phone": "01033334444"})
    sent.clear()  # 등록 확인 문자 2건은 제외

    confirm_url = client.post(f"{PREFIX}/safety/fall-events", json=FALL_REPORT).json()["confirmUrl"]

    assert [to for to, _ in sent] == ["01033334444"]
    assert "김사용님 댁" in sent[0][1]
    assert confirm_url in sent[0][1]


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

    # 재실 정책과 달리 단계 없이 즉시 전원 차단
    assert published[-1]["type"] == "turn_off"
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
    client.put(f"{PREFIX}/policies/fall-safety", json={"autoReportSec": 1})
    incident_id = client.post(f"{PREFIX}/safety/fall-events", json=FALL_REPORT).json()["incidentId"]

    status = "pending"
    for _ in range(40):  # 최대 4초 대기
        status = client.get(f"{PREFIX}/fall-incidents/{incident_id}").json()["status"]
        if status != "pending":
            break
        time.sleep(0.1)

    assert status == "auto_reported"
    assert "fall_auto_reported" in _event_types(client)


def test_unknown_fall_incident_is_404(client):
    assert client.get(f"{PREFIX}/fall-incidents/nope").status_code == 404
    assert client.post(f"{PREFIX}/fall-incidents/nope/resolve", params={"token": "x"}).status_code == 404
