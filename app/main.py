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

from app import db, edge_service, fall_service, mqtt_client, state_store, voice_service, weather_service, ws_hub
from app.config import settings
from app.routers import ai, dashboard, device, home_devices, sensing, stream, voice, weather

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

API_VERSION = "0.11.0"

# 태그 순서/설명: Swagger UI에서 이 순서 그대로 큰 섹션 헤더로 표시됩니다.
# 각 엔드포인트의 태그는 app/routers/*.py 의 데코레이터(tags=[...])에서 지정합니다.
TAGS_METADATA = [
    {
        "name": "회원 정보",
        "description": "사용자·보호자 연락처 등록·조회와 문자 발송 이력. 등록 시 해당 번호로 확인 문자가 가고, "
        "낙상 사고 발생 시에는 보호자 번호로 문자가 발송됩니다.",
    },
    {
        "name": "낙상 사고 감지",
        "description": "낙상 감지 AI 모델의 보고 접수, 보호자의 해결/신고 처리, 자동 신고 정책.",
    },
    {
        "name": "AI 중앙 제어",
        "description": "AI 중앙 판정 엔진 연동. 판단에 쓸 기기 상태·최종 재실 판단 결과 조회, 판단 결과 수신(서버가 가전 제어 실행), "
        "판단 기록과 사용자 피드백 조회. 취침 소등, 부재 시 화구 차단·화력 복구, 낙상, 물 출수 시나리오를 처리합니다.",
    },
    {
        "name": "음성 명령",
        "description": "대시보드 음성 명령(인식된 전체 문장) 수신과 AI 판정 엔진 전달, 확인 창 처리, 기록 조회. "
        "진행 상황은 WebSocket voice.status로 알립니다 (docs/VOICE.md).",
    },
    {
        "name": "AI 재실 판단",
        "description": "재실 판단 결과 저장·대시보드 전달과 안전 기준값(과열, 오프라인 판정). "
        "가전 제어 판단은 하지 않습니다 (AI 중앙 제어 참고).",
    },
    {
        "name": "인덕션 제어",
        "description": "화구 제어 명령과 인덕션 상태 조회. 가전 <-> 서버 통신 자체는 MQTT로 이루어지며, "
        "상태 조회는 서버가 받아둔 최신 값을 돌려줍니다.",
    },
    {
        "name": "가전 제어",
        "description": "전등·정수기·환풍기·공기청정기와 전체 가전 목록 조회, 사용자의 직접 제어. 가전과 서버 사이 통신은 MQTT입니다.",
    },
    {
        "name": "대시보드 화면",
        "description": "대시보드 초기 로딩용 전체 상태, 조리 세션, 날씨 안내 조회. "
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
    voice_service.resume_pending()           # 판단·확인을 기다리던 음성 명령의 시간 초과 타이머 다시 걸기
    mqtt_client.start()
    weather_task = None
    if settings.WEATHER_ENABLED:             # 날씨를 주기적으로 미리 받아 캐시 (인터넷 불안정 대비)
        weather_task = asyncio.create_task(weather_service.run_refresh_loop())
    edge_task = None
    if settings.EDGE_COMBINED_ENABLED:       # 엣지 노드 메시지를 합쳐 주기적으로 발행 (재실 판단 담당 입력)
        edge_task = asyncio.create_task(edge_service.run_combined_loop())
    yield
    # --- 서버가 종료될 때 ---
    for task in (weather_task, edge_task):
        if task is not None:
            task.cancel()
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
app.include_router(home_devices.router, prefix=settings.API_PREFIX)
app.include_router(ai.router, prefix=settings.API_PREFIX)
app.include_router(sensing.router, prefix=settings.API_PREFIX)
app.include_router(weather.router, prefix=settings.API_PREFIX)
app.include_router(voice.router, prefix=settings.API_PREFIX)
app.include_router(stream.router, prefix=settings.API_PREFIX)


@app.get("/health")
def health_check():
    """서버가 살아있는지 확인하는 가장 기본적인 엔드포인트.
    storage: "mongodb"면 DB에 저장 중, "memory"면 DB 없이 동작 중(재시작 시 데이터 소실)."""
    return {"status": "ok", "storage": db.storage_name()}
