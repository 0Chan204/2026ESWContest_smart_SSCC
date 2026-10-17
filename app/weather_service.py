"""
날씨 안내 서비스입니다. (v0.3.2)

대회장 인터넷이 불안정하므로, 안내 요청이 올 때 날씨를 받으러 나가지 않습니다.
- run_refresh_loop(): 서버가 켜져 있는 동안 WEATHER_REFRESH_SEC(기본 30분)마다 Open-Meteo에서
  날씨를 받아 메모리와 DB(runtime_state)에 저장합니다. 실패하면 WEATHER_RETRY_SEC 뒤 다시 시도합니다.
- build_briefing(): 저장해 둔 날씨로 안내 문장을 만듭니다. 인터넷이 끊겨도 마지막으로 받은 날씨로
  안내하고, 오래된 날씨면 "몇 시 기준"을 붙입니다. 한 번도 못 받았으면 못 가져왔다고 안내합니다.
- 시간대별 예보(v0.4.3): 지금 시간부터 WEATHER_HOURLY_HOURS(기본 12)시간치를 weather.hourly로 줍니다.
  응답할 때 이미 지나간 시간은 빼므로, 인터넷이 끊겨 갱신이 밀려도 지난 예보를 보여주지 않습니다.

Open-Meteo는 API 키가 필요 없습니다. 위치는 .env의 WEATHER_LAT / WEATHER_LON / WEATHER_LOCATION_NAME.
"""

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

import requests

from app import state_store
from app.config import settings
from app.schemas import HourlyWeather, WeatherBriefing, WeatherSnapshot

logger = logging.getLogger("induction.weather")

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"
KST = timezone(timedelta(hours=9))

# WMO 날씨 코드 -> 한국어 (https://open-meteo.com/en/docs 의 Weather variable documentation)
_CONDITIONS: dict[int, str] = {
    0: "맑음",
    1: "대체로 맑음",
    2: "구름 조금",
    3: "흐림",
    45: "안개",
    48: "안개",
    51: "약한 이슬비",
    53: "이슬비",
    55: "강한 이슬비",
    56: "어는 이슬비",
    57: "어는 이슬비",
    61: "약한 비",
    63: "비",
    65: "강한 비",
    66: "어는 비",
    67: "어는 비",
    71: "약한 눈",
    73: "눈",
    75: "강한 눈",
    77: "싸락눈",
    80: "약한 소나기",
    81: "소나기",
    82: "강한 소나기",
    85: "약한 눈보라",
    86: "강한 눈보라",
    95: "뇌우",
    96: "우박을 동반한 뇌우",
    99: "우박을 동반한 뇌우",
}


def condition_of(code: int) -> str:
    return _CONDITIONS.get(code, "알 수 없음")


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# 날씨 받아오기
# ---------------------------------------------------------------------------

def _first(values: Optional[list]) -> Optional[float]:
    return values[0] if values else None


def _at(values: Optional[list], index: int):
    return values[index] if values and index < len(values) else None


def _parse_hourly(body: dict, current_time: str) -> Optional[list[HourlyWeather]]:
    """Open-Meteo hourly 값에서 지금 시간(current_time이 속한 시간)부터 WEATHER_HOURLY_HOURS개를 고릅니다.

    Open-Meteo는 timezone=Asia/Seoul로 요청하면 "2026-10-17T20:00"처럼 시간대 없는 현지 시각을 주므로,
    응답의 utc_offset_seconds로 시간대를 붙여 프론트(브라우저)가 헷갈리지 않게 합니다.
    """
    hourly = body.get("hourly") or {}
    times = hourly.get("time") or []
    if not times:
        return None

    tz = timezone(timedelta(seconds=int(body.get("utc_offset_seconds", 9 * 3600))))
    start = current_time[:13]  # "2026-10-17T19:30" -> "2026-10-17T19" (그 시간의 시작부터)
    temps = hourly.get("temperature_2m")
    codes = hourly.get("weather_code")
    probs = hourly.get("precipitation_probability")

    items: list[HourlyWeather] = []
    for i, local_time in enumerate(times):
        if local_time[:13] < start:
            continue
        temperature, code = _at(temps, i), _at(codes, i)
        if temperature is None or code is None:
            continue
        items.append(
            HourlyWeather(
                time=datetime.fromisoformat(local_time).replace(tzinfo=tz).isoformat(timespec="seconds"),
                temperature=float(temperature),
                weatherCode=int(code),
                condition=condition_of(int(code)),
                precipitationProbability=_at(probs, i),
            )
        )
        if len(items) >= settings.WEATHER_HOURLY_HOURS:
            break
    return items


def parse_open_meteo(body: dict) -> WeatherSnapshot:
    """Open-Meteo 응답(JSON)을 저장용 형태로 바꿉니다. 필요한 값이 없으면 KeyError/TypeError"""
    current = body["current"]
    daily = body.get("daily", {})
    code = int(current["weather_code"])
    return WeatherSnapshot(
        location=settings.WEATHER_LOCATION_NAME,
        latitude=settings.WEATHER_LAT,
        longitude=settings.WEATHER_LON,
        observedAt=current["time"],
        fetchedAt=_now().isoformat(timespec="seconds"),
        temperature=float(current["temperature_2m"]),
        apparentTemperature=current.get("apparent_temperature"),
        humidity=current.get("relative_humidity_2m"),
        weatherCode=code,
        condition=condition_of(code),
        tempMax=_first(daily.get("temperature_2m_max")),
        tempMin=_first(daily.get("temperature_2m_min")),
        precipitationProbability=_first(daily.get("precipitation_probability_max")),
        hourly=_parse_hourly(body, current["time"]),
    )


def fetch_weather() -> WeatherSnapshot:
    """Open-Meteo에서 현재·오늘·시간대별 날씨를 받습니다. 실패하면 예외를 그대로 던집니다."""
    params = {
        "latitude": settings.WEATHER_LAT,
        "longitude": settings.WEATHER_LON,
        "current": "temperature_2m,relative_humidity_2m,apparent_temperature,weather_code",
        "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max",
        "hourly": "temperature_2m,weather_code,precipitation_probability",
        "timezone": "Asia/Seoul",
        # 밤에도 12시간치 예보가 나오도록 내일까지 받습니다 (daily는 첫 번째 값 = 오늘만 씁니다)
        "forecast_days": 2,
    }
    response = requests.get(OPEN_METEO_URL, params=params, timeout=settings.WEATHER_TIMEOUT_SEC)
    response.raise_for_status()
    return parse_open_meteo(response.json())


def refresh() -> bool:
    """날씨를 새로 받아 저장합니다. 실패해도 예외를 던지지 않고 기존 저장값을 그대로 둡니다."""
    try:
        snapshot = fetch_weather()
    except Exception as exc:  # 네트워크 끊김, 응답 형식 변경 등
        logger.warning("날씨를 가져오지 못했습니다. 마지막으로 저장된 날씨를 계속 사용합니다: %s", exc)
        return False
    state_store.set_weather(snapshot)
    logger.info("날씨 갱신: %s %s %.1f도", snapshot.location, snapshot.condition, snapshot.temperature)
    return True


async def run_refresh_loop() -> None:
    """서버 시작 시 백그라운드로 실행됩니다. 문자처럼 HTTP 요청이 이벤트 루프를 막지 않도록 별도 스레드에서 받습니다."""
    while True:
        ok = await asyncio.to_thread(refresh)
        await asyncio.sleep(settings.WEATHER_REFRESH_SEC if ok else settings.WEATHER_RETRY_SEC)


# ---------------------------------------------------------------------------
# 안내 문장 만들기
# ---------------------------------------------------------------------------

def _topic_particle(word: str) -> str:
    """'서울' -> '서울은', '부산' -> '부산은', '대구' -> '대구는' (받침 유무로 은/는 선택)"""
    last = word[-1] if word else ""
    if "가" <= last <= "힣":
        return word + ("은" if (ord(last) - ord("가")) % 28 else "는")
    return word + "은(는)"


def _deg(value: float) -> str:
    return f"{round(value)}도"


def _tip(snapshot: WeatherSnapshot) -> Optional[str]:
    hot = snapshot.temperature >= 28 or (snapshot.tempMax is not None and snapshot.tempMax >= 30)
    if hot:
        return "더운 날이니 물을 자주 드세요."
    if snapshot.humidity is not None and snapshot.humidity <= 35:
        return "공기가 건조하니 물을 자주 드세요."
    if snapshot.precipitationProbability is not None and snapshot.precipitationProbability >= 60:
        return "외출하실 때 우산을 챙기세요."
    return None


def _based_on_text(fetched: datetime) -> str:
    local = fetched.astimezone(KST)
    ampm = "오전" if local.hour < 12 else "오후"
    hour = local.hour % 12 or 12
    return f"{ampm} {hour}시 {local.minute:02d}분 기준"


def _upcoming(hourly: list[HourlyWeather], now: datetime) -> list[HourlyWeather]:
    """이미 끝난 시간(시작 + 1시간 <= 지금)의 예보는 뺍니다."""
    upcoming = []
    for item in hourly:
        try:
            ends_at = datetime.fromisoformat(item.time) + timedelta(hours=1)
        except ValueError:
            continue
        if ends_at.tzinfo is not None and ends_at > now:
            upcoming.append(item)
    return upcoming


def build_briefing(snapshot: Optional[WeatherSnapshot] = None) -> WeatherBriefing:
    snapshot = snapshot or state_store.get_weather()
    if snapshot is None:
        return WeatherBriefing(available=False, text="날씨 정보를 아직 가져오지 못했어요.")
    if snapshot.hourly is not None:
        snapshot = snapshot.model_copy(update={"hourly": _upcoming(snapshot.hourly, _now())})

    try:
        fetched = datetime.fromisoformat(snapshot.fetchedAt)
        stale = (_now() - fetched).total_seconds() > settings.WEATHER_STALE_SEC
    except ValueError:
        fetched, stale = None, True

    parts = [f"현재 {_topic_particle(snapshot.location)} {snapshot.condition}, 기온 {_deg(snapshot.temperature)}예요."]
    if snapshot.tempMax is not None and snapshot.tempMin is not None:
        today = f"오늘 최고 {_deg(snapshot.tempMax)}, 최저 {_deg(snapshot.tempMin)}"
        if snapshot.precipitationProbability is not None:
            today += f"이고 비 올 확률은 {round(snapshot.precipitationProbability)}%예요."
        else:
            today += "예요."
        parts.append(today)
    tip = _tip(snapshot)
    if tip:
        parts.append(tip)

    text = " ".join(parts)
    if stale and fetched is not None:
        text = f"({_based_on_text(fetched)}) {text}"
    return WeatherBriefing(available=True, text=text, stale=stale, basedOn=snapshot.fetchedAt, weather=snapshot)
