"""
날씨 안내(v0.3.2)를 검증하는 테스트입니다. 실제 날씨 서버에는 접속하지 않고 가짜 응답을 씁니다.
"""

import time
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app import db, state_store, weather_service
from app.config import settings
from app.schemas import WeatherSnapshot

PREFIX = settings.API_PREFIX

OPEN_METEO_BODY = {
    "latitude": 37.56,
    "longitude": 126.97,
    "current": {
        "time": "2026-10-16T21:45",
        "interval": 900,
        "temperature_2m": 18.3,
        "relative_humidity_2m": 60,
        "apparent_temperature": 17.1,
        "weather_code": 0,
    },
    "daily": {
        "time": ["2026-10-16"],
        "weather_code": [3],
        "temperature_2m_max": [22.4],
        "temperature_2m_min": [11.6],
        "precipitation_probability_max": [10],
    },
}


class FakeResponse:
    def __init__(self, body: dict):
        self._body = body

    def raise_for_status(self) -> None:
        pass

    def json(self) -> dict:
        return self._body


@pytest.fixture()
def weather_ok(monkeypatch):
    calls: list[dict] = []

    def fake_get(url, params=None, timeout=None):
        calls.append({"url": url, "params": params, "timeout": timeout})
        return FakeResponse(OPEN_METEO_BODY)

    monkeypatch.setattr(weather_service.requests, "get", fake_get)
    return calls


@pytest.fixture()
def weather_down(monkeypatch):
    def broken_get(*args, **kwargs):
        raise ConnectionError("network unreachable")

    monkeypatch.setattr(weather_service.requests, "get", broken_get)


def _snapshot(**changes) -> WeatherSnapshot:
    base = weather_service.parse_open_meteo(OPEN_METEO_BODY)
    return base.model_copy(update=changes)


# ---------------------------------------------------------------------------
# 받아오기 / 저장
# ---------------------------------------------------------------------------

def test_parse_open_meteo():
    snapshot = weather_service.parse_open_meteo(OPEN_METEO_BODY)
    assert snapshot.location == settings.WEATHER_LOCATION_NAME
    assert (snapshot.temperature, snapshot.humidity, snapshot.weatherCode) == (18.3, 60, 0)
    assert snapshot.condition == "맑음"
    assert (snapshot.tempMax, snapshot.tempMin, snapshot.precipitationProbability) == (22.4, 11.6, 10)
    assert snapshot.observedAt == "2026-10-16T21:45"


def test_refresh_requests_configured_location(weather_ok):
    assert weather_service.refresh() is True
    params = weather_ok[0]["params"]
    assert (params["latitude"], params["longitude"]) == (settings.WEATHER_LAT, settings.WEATHER_LON)
    assert weather_ok[0]["timeout"] == settings.WEATHER_TIMEOUT_SEC
    assert state_store.get_weather().temperature == 18.3


def test_refresh_failure_keeps_last_weather(monkeypatch, weather_ok):
    weather_service.refresh()

    def broken_get(*args, **kwargs):
        raise ConnectionError("network unreachable")

    monkeypatch.setattr(weather_service.requests, "get", broken_get)
    assert weather_service.refresh() is False
    assert state_store.get_weather().temperature == 18.3


# ---------------------------------------------------------------------------
# 안내 문장
# ---------------------------------------------------------------------------

def test_briefing_text():
    briefing = weather_service.build_briefing(_snapshot())
    assert briefing.available is True and briefing.stale is False
    assert briefing.text == "현재 서울은 맑음, 기온 18도예요. 오늘 최고 22도, 최저 12도이고 비 올 확률은 10%예요."


def test_briefing_without_any_weather():
    briefing = weather_service.build_briefing()
    assert briefing.available is False
    assert briefing.text == "날씨 정보를 아직 가져오지 못했어요."
    assert briefing.weather is None


def test_old_weather_says_when_it_was_fetched():
    fetched = datetime(2026, 10, 16, 6, 5, tzinfo=timezone.utc)  # 한국 시각 오후 3시 5분
    briefing = weather_service.build_briefing(_snapshot(fetchedAt=fetched.isoformat()))
    assert briefing.stale is True
    assert briefing.text.startswith("(오후 3시 05분 기준) 현재 서울은 맑음")


@pytest.mark.parametrize(
    "changes, tip",
    [
        ({"temperature": 29.0}, "더운 날이니 물을 자주 드세요."),
        ({"humidity": 30}, "공기가 건조하니 물을 자주 드세요."),
        ({"precipitationProbability": 70}, "외출하실 때 우산을 챙기세요."),
    ],
)
def test_briefing_tips(changes, tip):
    assert weather_service.build_briefing(_snapshot(**changes)).text.endswith(tip)


def test_location_particle(monkeypatch):
    assert weather_service.build_briefing(_snapshot(location="대구")).text.startswith("현재 대구는 맑음")
    assert weather_service.build_briefing(_snapshot(location="Seoul")).text.startswith("현재 Seoul은(는) 맑음")


# ---------------------------------------------------------------------------
# API / AI 판단 연동
# ---------------------------------------------------------------------------

def test_weather_api(client, weather_ok):
    assert client.get(f"{PREFIX}/weather").json()["available"] is False

    body = client.get(f"{PREFIX}/weather", params={"refresh": True}).json()
    assert body["available"] is True
    assert body["weather"]["condition"] == "맑음"
    assert body["text"].startswith("현재 서울은 맑음")


def test_weather_api_refresh_without_internet_uses_last_weather(client, weather_down):
    state_store.set_weather(_snapshot())
    body = client.get(f"{PREFIX}/weather", params={"refresh": True}).json()
    assert body["available"] is True
    assert body["weather"]["temperature"] == 18.3


def test_water_dispense_with_weather_briefing(client, published):
    state_store.set_weather(_snapshot())
    res = client.post(
        f"{PREFIX}/ai/decisions",
        json={
            "decisionId": "d-water-weather",
            "scenario": "water_dispense",
            "confidence": 0.9,
            "timestamp": "2026-10-16T12:00:00+00:00",
            "room": "kitchen",
            "actions": [{"device": "water_purifier", "action": "dispense", "amountMl": 250}],
            "weatherBriefing": True,
        },
    ).json()
    assert res["actions"][0]["status"] == "sent"
    assert res["weather"]["available"] is True
    assert res["weather"]["text"].startswith("현재 서울은 맑음")
    # 판단 기록에도 남는다
    assert client.get(f"{PREFIX}/ai/decisions/d-water-weather").json()["weather"]["text"] == res["weather"]["text"]


def test_weather_briefing_without_weather_still_dispenses(client, published):
    res = client.post(
        f"{PREFIX}/ai/decisions",
        json={
            "decisionId": "d-water-noweather",
            "scenario": "water_dispense",
            "confidence": 0.9,
            "timestamp": "2026-10-16T12:00:00+00:00",
            "actions": [{"device": "water_purifier", "action": "dispense", "amountMl": 250}],
            "weatherBriefing": True,
        },
    ).json()
    assert res["actions"][0]["status"] == "sent"
    assert res["weather"]["available"] is False
    assert [c["type"] for c in published] == ["dispense"]


def test_no_weather_unless_requested(client, published):
    state_store.set_weather(_snapshot())
    res = client.post(
        f"{PREFIX}/ai/decisions",
        json={
            "decisionId": "d-light",
            "scenario": "bedtime_light_off",
            "confidence": 0.9,
            "timestamp": "2026-10-16T12:00:00+00:00",
            "actions": [{"device": "light", "action": "off"}],
        },
    ).json()
    assert res["weather"] is None


# ---------------------------------------------------------------------------
# 서버 시작 시 자동 갱신 / 재시작 후 유지
# ---------------------------------------------------------------------------

def test_server_fetches_weather_on_start(monkeypatch, published, weather_ok):
    from app.main import app

    monkeypatch.setattr(settings, "WEATHER_ENABLED", True, raising=False)
    with TestClient(app):
        for _ in range(40):
            if state_store.get_weather() is not None:
                break
            time.sleep(0.05)
    assert state_store.get_weather() is not None
    assert len(weather_ok) == 1


def test_weather_survives_restart(mongo, published):
    from app.main import app

    state_store.set_weather(_snapshot())
    db.flush()
    state_store.reset_memory()
    assert state_store.get_weather() is None

    with TestClient(app) as client:
        body = client.get(f"{PREFIX}/weather").json()
    assert body["available"] is True
    assert body["weather"]["temperature"] == 18.3
