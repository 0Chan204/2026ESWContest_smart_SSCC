"""
FastAPI 애플리케이션의 진입점입니다.
실행 명령: uvicorn app.main:app --reload

v0.2: 하나의 Swagger 문서(/docs) 안에서 태그 기준으로 "device"(인덕션)와
"dashboard"(프론트+AI모델) 두 개의 큰 섹션으로 묶어서 보여줍니다.
(별도 URL로 쪼개지 않고, FastAPI/Swagger UI가 태그별로 자동으로 접었다 펼 수
 있는 섹션을 만들어주는 기본 기능을 그대로 사용합니다.)
"""

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app import mqtt_client, ws_hub
from app.config import settings
from app.routers import dashboard, device, stream

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

API_VERSION = "0.2.0"

# 태그 순서/설명: Swagger UI에서 이 순서 그대로 큰 섹션 헤더로 표시됩니다.
TAGS_METADATA = [
    {
        "name": "device",
        "description": "인덕션(디바이스) 관련 API. 가전 <-> 서버 통신은 MQTT로 이루어지며, "
        "여기 있는 REST는 서버가 캐시해둔 값을 조회하는 디버그/운영용입니다.",
    },
    {
        "name": "dashboard",
        "description": "프론트 대시보드 및 AI 재실 판단 모델이 호출하는 API입니다.",
    },
]


@asynccontextmanager
async def lifespan(app: FastAPI):
    # --- 서버가 시작될 때 ---
    ws_hub.bind_loop(asyncio.get_running_loop())
    mqtt_client.start()
    yield
    # --- 서버가 종료될 때 ---
    mqtt_client.stop()


app = FastAPI(
    title="HomeVIS Induction Backend",
    description="ESWC 스마트가전 프로젝트 - 인덕션 담당 백엔드 (FastAPI + MQTT)",
    version=API_VERSION,
    lifespan=lifespan,
    openapi_tags=TAGS_METADATA,
)

app.include_router(device.router, prefix=settings.API_PREFIX)
app.include_router(dashboard.router, prefix=settings.API_PREFIX)
app.include_router(stream.router, prefix=settings.API_PREFIX)


@app.get("/health")
def health_check():
    """서버가 살아있는지 확인하는 가장 기본적인 엔드포인트."""
    return {"status": "ok"}
