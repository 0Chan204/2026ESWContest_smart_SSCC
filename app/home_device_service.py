"""
전등·정수기·환풍기 제어와 상태 처리를 담당합니다. (v0.3, v0.5: 환풍기·전등 밝기)

인덕션은 기존 commands_service / device_service가 그대로 처리하고,
여기서는 그 외 가전(전등, 정수기, 환풍기)만 다룹니다. 흐름은 인덕션과 같습니다.

전등 밝기(v0.5): on = 100%, off = 꺼짐, fadeout = 절전 밝기(LIGHT_SAVING_BRIGHTNESS, 20%)로
LIGHT_FADE_SEC초에 걸쳐 서서히 낮춤(power는 on 유지). 절전 판단은 AI 판정 엔진이 하고(power_saving),
실행은 app/ai_service.py가 합니다.

1) dispatch(): 명령 검증 -> CommandRecord 저장 -> MQTT command 토픽 발행
2) handle_state(): 가전이 state 토픽으로 보낸 상태 저장 + 대시보드 실시간 전달
3) handle_ack(): 가전이 ack 토픽으로 보낸 처리 결과를 명령 기록에 반영
"""

import logging
from typing import Literal, Optional

from pydantic import ValidationError

from app import device_registry, state_store, ws_hub
from app.commands_service import CommandRejected
from app.config import settings
from app.rules import current_timestamp_iso, generate_command_id
from app.schemas import (
    CommandRecord,
    FanState,
    HomeDeviceAck,
    HomeDeviceCommandOut,
    HomeDeviceCommandRequest,
    LightState,
    WaterPurifierState,
)

logger = logging.getLogger("induction.home_devices")

# 가전 종류별로 받을 수 있는 명령
ALLOWED_COMMANDS = {
    device_registry.LIGHT: ("on", "off", "blink", "fadeout"),
    device_registry.WATER_PURIFIER: ("dispense",),
    device_registry.FAN: ("on", "off", "set_speed"),
}
_STATE_MODELS = {
    device_registry.LIGHT: LightState,
    device_registry.WATER_PURIFIER: WaterPurifierState,
    device_registry.FAN: FanState,
}
LIGHT_FULL_BRIGHTNESS = 100


class UnknownDevice(Exception):
    pass


def dispatch(
    device_id: str,
    request: HomeDeviceCommandRequest,
    actor: Literal["user", "system", "ai"] = "user",
    reason: Optional[str] = None,
    decision_id: Optional[str] = None,
) -> CommandRecord:
    """명령을 검증하고 MQTT로 보냅니다.
    없는 기기면 UnknownDevice, 그 기기가 받을 수 없는 명령이면 CommandRejected를 던집니다."""
    device = device_registry.get_device(device_id)
    if device is None or device.type not in ALLOWED_COMMANDS:
        raise UnknownDevice(device_id)

    allowed = ALLOWED_COMMANDS[device.type]
    if request.type not in allowed:
        raise CommandRejected([f"'{device_id}'({device.type})는 {request.type} 명령을 받을 수 없습니다. 가능: {', '.join(allowed)}"])
    if request.type == "dispense" and request.amountMl is None:
        raise CommandRejected(["dispense 명령에는 출수량(amountMl)이 필요합니다."])
    if request.type == "set_speed" and request.speed is None:
        raise CommandRejected(["set_speed 명령에는 풍량(speed: low / mid / high)이 필요합니다."])

    is_light = device.type == device_registry.LIGHT
    duration_sec = None
    if request.type == "blink":
        duration_sec = request.durationSec or settings.LIGHT_BLINK_SEC
    elif request.type == "fadeout":
        duration_sec = request.durationSec or settings.LIGHT_FADE_SEC

    brightness = None
    if is_light and request.type == "on":
        brightness = LIGHT_FULL_BRIGHTNESS
    elif request.type == "fadeout":
        brightness = settings.LIGHT_SAVING_BRIGHTNESS

    command = HomeDeviceCommandOut(
        commandId=generate_command_id(),
        issuedAt=current_timestamp_iso(),
        deviceId=device_id,
        type=request.type,
        durationSec=duration_sec,
        amountMl=request.amountMl if request.type == "dispense" else None,
        brightness=brightness,
        speed=request.speed if request.type == "set_speed" else None,
    )
    record = CommandRecord(
        commandId=command.commandId,
        status="pending",
        type=command.type,
        actor=actor,
        reason=reason,
        issuedAt=command.issuedAt,
        deviceId=device_id,
        deviceType=device.type,
        durationSec=command.durationSec,
        amountMl=command.amountMl,
        decisionId=decision_id,
        brightness=command.brightness,
        speed=command.speed,
    )
    state_store.save_command(record)
    if is_light and request.type == "fadeout":
        # 절전 밝기로 낮춘 전등: 사람이 돌아오면(power_saving_end) 100%로 되돌릴 대상
        state_store.set_power_saving_light(device_id, True)
    elif is_light and request.type in ("on", "off"):
        # 누가 켜거나 끄면 절전 상태가 아니게 됩니다 (사용자가 직접 끈 전등은 복귀 때 다시 켜지 않음).
        # blink는 잠깐 깜빡인 뒤 원래 상태로 돌아가므로 절전 표시를 그대로 둡니다.
        state_store.set_power_saving_light(device_id, False)

    from app import mqtt_client  # 지연 import: 순환 참조 방지

    try:
        mqtt_client.publish_device_command(device_id, command.model_dump(exclude_none=True))
    except Exception:
        state_store.update_command(command.commandId, status="failed")
        raise

    return state_store.update_command(command.commandId, status="sent") or record


def handle_state(device_id: str, device_type: str, payload: dict) -> None:
    model = _STATE_MODELS.get(device_type)
    if model is None:
        return
    try:
        state = model.model_validate(payload)
    except ValidationError as exc:
        logger.error("잘못된 형식의 상태 메시지 무시 (device=%s): %s", device_id, exc)
        return
    body = state.model_dump()
    state_store.save_device_state(device_id, device_type, body)
    ws_hub.broadcast_threadsafe("device.state", {"deviceId": device_id, "device": device_type, "state": body})


def handle_ack(device_id: str, device_type: str, payload: dict) -> None:
    try:
        ack = HomeDeviceAck.model_validate(payload)
    except ValidationError as exc:
        logger.error("잘못된 형식의 ack 메시지 무시 (device=%s): %s", device_id, exc)
        return

    new_status = {"applied": "acked", "rejected": "rejected", "failed": "failed"}.get(ack.result, "failed")
    record = state_store.update_command(ack.commandId, status=new_status, ackedAt=ack.appliedAt)
    if record is None:
        logger.warning("알 수 없는 commandId(%s)에 대한 ack 수신 (device=%s)", ack.commandId, device_id)
    if ack.state is not None:
        handle_state(device_id, device_type, ack.state)

    ws_hub.broadcast_threadsafe(
        "command.result",
        {
            "deviceId": device_id,
            "commandId": ack.commandId,
            "status": new_status,
            "result": ack.result,
            "appliedAt": ack.appliedAt,
        },
    )
