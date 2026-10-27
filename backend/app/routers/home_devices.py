"""
전등·정수기·환풍기 조회와 직접 제어 REST API입니다. (v0.3, v0.5: 환풍기. Swagger 섹션: 전등·정수기·환풍기 제어)

가전과 서버 사이 통신은 MQTT이고(app/device_registry.py 토픽 규칙), 여기는 대시보드가
기기 목록·상태를 보고 사용자가 직접 제어할 때 쓰는 창구입니다.
인덕션 제어는 기존 POST /appliances/{id}/burners/{burnerId}/commands 를 그대로 씁니다.
"""

from fastapi import APIRouter, HTTPException, status

from app import ai_service, commands_service, device_registry, home_device_service
from app.schemas import DeviceCommandAccepted, DeviceInfo, DeviceListResponse, HomeDeviceCommandRequest

TAG = "가전 제어"
router = APIRouter(prefix="/devices")


@router.get("", response_model=DeviceListResponse, tags=[TAG], summary="전체 가전 목록과 상태 조회")
def list_devices() -> DeviceListResponse:
    return DeviceListResponse(items=ai_service.get_device_states())


@router.get("/{device_id}", response_model=DeviceInfo, tags=[TAG], summary="가전 1대 상태 조회")
def read_device(device_id: str) -> DeviceInfo:
    device = device_registry.get_device(device_id)
    if device is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="등록되지 않은 기기입니다.")
    return ai_service.get_device_info(device)


@router.post("/{device_id}/commands", response_model=DeviceCommandAccepted, status_code=status.HTTP_202_ACCEPTED, tags=[TAG], summary="전등·정수기·환풍기·공기청정기 제어 명령 전송")
def send_device_command(device_id: str, request: HomeDeviceCommandRequest) -> DeviceCommandAccepted:
    """
    - 전등: on(밝기 100%) / off / blink(durationSec, 기본 10초) / fadeout(절전 밝기 20%로 서서히, power는 on 유지)
    - 정수기: dispense(amountMl 필수)
    - 환풍기: on / off / set_speed(speed: low·mid·high = 약·중·강, 필수)
    - 공기청정기: on / off / set_mode(mode: auto·manual, 필수). 공기질 자동 작동은 기기가 스스로 판단합니다.

    사용자가 전등을 직접 켜거나 끄면 절전 상태가 풀려, 사람이 돌아와도(power_saving_end) 다시 켜지 않습니다.
    """
    device = device_registry.get_device(device_id)
    if device is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="등록되지 않은 기기입니다.")
    if device.type == device_registry.STOVE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="인덕션은 POST /appliances/{id}/burners/{burnerId}/commands 로 제어합니다.",
        )
    try:
        record = home_device_service.dispatch(device_id, request, actor="user")
    except commands_service.CommandRejected as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "COMMAND_REJECTED", "details": {"reasons": exc.reasons}},
        ) from exc
    return DeviceCommandAccepted(commandId=record.commandId, deviceId=device_id, issuedAt=record.issuedAt)
