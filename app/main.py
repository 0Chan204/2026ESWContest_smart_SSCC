"""
FastAPI 애플리케이션의 진입점입니다.
실행 명령: uvicorn app.main:app --reload

v0.2: Swagger 문서를 "인덕션(디바이스)"와 "프론트 대시보드"로 분리했습니다.
실제 REST 경로(app.include_router에 붙는 prefix)는 하나로 통일하고,
문서(OpenAPI 스키마)만 태그 기준으로 두 개를 따로 만드는 방식입니다.
(경로를 두 앱으로 쪼개면 프론트가 이미 합의한 경로 앞에 prefix가 붙어버려서
 명세와 어긋나기 때문에, 이 방식이 더 안전합니다.)

- /docs/device    -> 인덕션(디바이스) 관련 API 문서
- /docs/dashboard -> 프론트 대시보드 / AI 모델 관련 API 문서
"""

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.openapi.utils import get_openapi

from app import mqtt_client, ws_hub
from app.config import settings
from app.routers import dashboard, device, stream

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

API_VERSION = "0.2.0"


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
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)

app.include_router(device.router, prefix=settings.API_PREFIX)
app.include_router(dashboard.router, prefix=settings.API_PREFIX)
app.include_router(stream.router, prefix=settings.API_PREFIX)


@app.get("/health")
def health_check():
    """서버가 살아있는지 확인하는 가장 기본적인 엔드포인트."""
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# 분리된 Swagger 문서: 인덕션(디바이스) / 프론트 대시보드
# ---------------------------------------------------------------------------

def _filtered_openapi(title: str, description: str, tag: str) -> dict:
    routes = [r for r in app.routes if tag in (getattr(r, "tags", None) or [])]
    return get_openapi(title=title, version=API_VERSION, description=description, routes=routes)


@app.get("/openapi/device.json", include_in_schema=False)
def device_openapi():
    return _filtered_openapi(
        "HomeVIS - 인덕션(디바이스) API",
        "가전 <-> 서버는 MQTT로 통신합니다. 여기 있는 REST는 서버가 캐시한 값을 읽는 디버그/조회용입니다.",
        "device",
    )


@app.get("/docs/device", include_in_schema=False)
def device_docs():
    return get_swagger_ui_html(openapi_url="/openapi/device.json", title="HomeVIS - 인덕션(디바이스) API 문서")


@app.get("/openapi/dashboard.json", include_in_schema=False)
def dashboard_openapi():
    return _filtered_openapi(
        "HomeVIS - 프론트 대시보드 API",
        "프론트(대시보드) 및 AI 재실 판단 모델이 호출하는 API입니다.",
        "dashboard",
    )


@app.get("/docs/dashboard", include_in_schema=False)
def dashboard_docs():
    return get_swagger_ui_html(openapi_url="/openapi/dashboard.json", title="HomeVIS - 프론트 대시보드 API 문서")
