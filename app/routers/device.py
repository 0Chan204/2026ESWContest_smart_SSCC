"""
인덕션(가전) 관련 디버그/조회용 REST API입니다.

주의: 가전 자체는 이 REST API를 호출하지 않습니다! 가전 <-> 서버 통신은
전부 MQTT(telemetry/ack/command 토픽)로 이루어집니다 (app/mqtt_client.py 참고).
여기 있는 엔드포인트는 어디까지나 "서버가 MQTT로 받아 캐시해둔 값을 조회"하기 위한
운영/디버그 창구이며, Swagger 문서를 인덕션 쪽과 프론트 쪽으로 분리하기 위해
별도 태그("device")로 묶어 관리합니다.
"""

from fastapi import APIRouter, HTTPException, status

from app import state_store
from app.schemas import TelemetryReport

router = APIRouter(prefix="/devices", tags=["device"])


@router.get("/{device_id}/telemetry", response_model=TelemetryReport)
def read_telemetry(device_id: str) -> TelemetryReport:
    """가전이 MQTT telemetry 토픽으로 마지막에 보고한 상태를 조회합니다."""
    telemetry = state_store.get_telemetry(device_id)
    if telemetry is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"'{device_id}' 가전의 telemetry를 아직 받지 못했습니다.",
        )
    return telemetry


@router.get("/{device_id}/status")
def read_status(device_id: str) -> dict:
    """온라인/오프라인 판정 (마지막 telemetry 수신 후 heartbeatTimeoutSec 경과 여부로 판단)."""
    last_seen = state_store.get_last_seen_at(device_id)
    return {
        "deviceId": device_id,
        "online": state_store.is_online(device_id),
        "lastSeenAt": last_seen.isoformat(timespec="seconds") if last_seen else None,
    }
