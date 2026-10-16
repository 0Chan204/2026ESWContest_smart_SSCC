"""
날씨 안내 조회 (v0.3.2). 실제 로직은 app/weather_service.py에 있습니다.
"""

from fastapi import APIRouter

from app import weather_service
from app.schemas import WeatherBriefing

router = APIRouter()


@router.get("/weather", response_model=WeatherBriefing, tags=["대시보드 화면"], summary="날씨 안내 조회")
def read_weather(refresh: bool = False) -> WeatherBriefing:
    """
    서버가 미리 받아 둔 날씨(기본 30분마다 갱신)로 만든 안내 문장과 날씨 값을 돌려줍니다.
    인터넷이 끊겨 있으면 마지막으로 받은 날씨로 안내하고, 오래된 값이면 stale=true와 함께
    문장 앞에 "몇 시 기준"을 붙입니다. 한 번도 못 받았으면 available=false입니다.

    refresh=true면 지금 바로 다시 받아온 뒤 안내합니다 (테스트용. 인터넷이 없으면 최대 5초 걸릴 수 있음).
    """
    if refresh:
        weather_service.refresh()
    return weather_service.build_briefing()
