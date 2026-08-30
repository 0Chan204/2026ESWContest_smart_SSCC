"""
FastAPI 애플리케이션의 진입점입니다.
실행 명령: uvicorn app.main:app --reload
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app import mqtt_client
from app.routers import induction

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # --- 서버가 시작될 때 ---
    mqtt_client.start()
    yield
    # --- 서버가 종료될 때 ---
    mqtt_client.stop()


app = FastAPI(
    title="HomeVIS Induction Backend",
    description="ESWC 스마트가전 프로젝트 - 인덕션 담당 백엔드 (FastAPI + MQTT)",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(induction.router)


@app.get("/health")
def health_check():
    """서버가 살아있는지 확인하는 가장 기본적인 엔드포인트."""
    return {"status": "ok"}
