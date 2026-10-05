"""
FastAPI 애플리케이션의 진입점입니다.
실행 명령: uvicorn app.main:app --reload

하나의 Swagger 문서(/docs) 안에서 기능별 태그로 섹션을 나눠서 보여줍니다.
(회원 정보 / 낙상 사고 감지 / AI 재실 판단 / 인덕션 제어 / 대시보드 화면 / 안전 이벤트)
별도 URL로 쪼개지 않고, Swagger UI가 태그별로 접었다 펼 수 있는 섹션을 만들어주는
기본 기능을 그대로 사용합니다.
"""

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app import db, fall_service, mqtt_client, state_store, ws_hub
from app.config import settings
from app.routers import dashboard, device, stream

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

API_VERSION = "0.2.0"

# 태그 순서/설명: Swagger UI에서 이 순서 그대로 큰 섹션 헤더로 표시됩니다.
# 각 엔드포인트의 태그는 app/routers/*.py 의 데코레이터(tags=[...])에서 지정합니다.
TAGS_METADATA = [
    {
        "name": "회원 정보",
        "description": "사용자·보호자 연락처 등록·조회. 등록 시 해당 번호로 확인 문자가 가고, "
        "낙상 사고 발생 시에는 보호자 번호로 문자가 발송됩니다.",
    },
    {
        "name": "낙상 사고 감지",
        "description": "낙상 감지 AI 모델의 보고 접수, 보호자의 해결/신고 처리, 자동 신고 정책.",
    },
    {
        "name": "AI 재실 판단",
        "description": "AI 재실 판단 모델의 보고 접수와 부재중 자동 제어(화력 저감/전원 차단) 정책.",
    },
    {
        "name": "인덕션 제어",
        "description": "화구 제어 명령과 인덕션 상태 조회. 가전 <-> 서버 통신 자체는 MQTT로 이루어지며, "
        "상태 조회는 서버가 받아둔 최신 값을 돌려줍니다.",
    },
    {
        "name": "대시보드 화면",
        "description": "대시보드 초기 로딩용 전체 상태와 조리 세션 조회. "
        "실시간 갱신은 WebSocket /api/v1/stream 을 사용합니다 (Swagger에는 표시되지 않음).",
    },
    {
        "name": "안전 이벤트",
        "description": "과열·부재중·낙상 등 안전 이벤트 이력 조회와 피드백.",
    },
]


@asynccontextmanager
async def lifespan(app: FastAPI):
    # --- 서버가 시작될 때 ---
    ws_hub.bind_loop(asyncio.get_running_loop())
    db.connect()                             # MongoDB 연결 (실패하거나 설정이 없으면 메모리로 동작)
    state_store.load_from_db()               # 저장돼 있던 데이터를 메모리로 불러오기
    fall_service.resume_pending_incidents()  # 응답 대기 중이던 낙상 사건의 타이머 다시 걸기
    mqtt_client.start()
    yield
    # --- 서버가 종료될 때 ---
    mqtt_client.stop()
    db.disconnect()                          # 아직 저장 안 된 쓰기를 마저 저장하고 연결 종료


app = FastAPI(
    title="HomeVIS",
    description="ESWC 스마트가전 프로젝트 HomeVIS 백엔드 (FastAPI + MQTT)",
    version=API_VERSION,
    lifespan=lifespan,
    openapi_tags=TAGS_METADATA,
)

app.include_router(device.router, prefix=settings.API_PREFIX)
app.include_router(dashboard.router, prefix=settings.API_PREFIX)
app.include_router(stream.router, prefix=settings.API_PREFIX)


@app.get("/health")
def health_check():
    """서버가 살아있는지 확인하는 가장 기본적인 엔드포인트.
    storage: "mongodb"면 DB에 저장 중, "memory"면 DB 없이 동작 중(재시작 시 데이터 소실)."""
    return {"status": "ok", "storage": db.storage_name()}
