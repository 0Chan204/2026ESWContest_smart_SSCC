"""
화구 제어 명령의 생애주기(발행 -> 전송 -> ack 반영)를 담당하는 서비스입니다.

흐름:
1) dispatch_command(): 프론트(또는 안전 정책 엔진)가 요청 -> 안전 규칙 검사 ->
   MQTT로 명령 발행 -> CommandRecord(status="sent") 저장
2) on_ack_received(): 가전이 MQTT ack 토픽으로 결과를 보내오면 -> CommandRecord 갱신
   -> WebSocket으로 command.result 이벤트 브로드캐스트
"""

import logging
from typing import Literal, Optional

from app import state_store, ws_hub
from app.rules import build_control_command, validate_burner_command
from app.schemas import AckReport, BurnerCommandRequest, CommandRecord

logger = logging.getLogger("induction.commands")


class CommandRejected(Exception):
    def __init__(self, reasons: list[str]):
        super().__init__("; ".join(reasons))
        self.reasons = reasons


def dispatch_command(
    device_id: str,
    burner_id: str,
    request: BurnerCommandRequest,
    actor: Literal["user", "system"] = "user",
    reason: Optional[str] = None,
) -> CommandRecord:
    """
    제어 명령을 검증하고 MQTT로 발행합니다.
    안전 규칙 위반 시 CommandRejected를 발생시킵니다 (라우터에서 409로 변환).
    """
    current_telemetry = state_store.get_telemetry(device_id)
    errors = validate_burner_command(current_telemetry, burner_id, request)
    if errors:
        raise CommandRejected(errors)

    command = build_control_command(burner_id, request)

    record = CommandRecord(
        commandId=command.commandId,
        status="pending",
        type=command.type,
        level=command.level,
        actor=actor,
        reason=reason,
        issuedAt=command.issuedAt,
        ackedAt=None,
    )
    state_store.save_command(record)

    from app import mqtt_client  # 지연 import: mqtt_client <-> device_service/commands_service 순환 참조 방지

    payload = command.model_dump(exclude_none=True)
    try:
        mqtt_client.publish_command(device_id, payload)
    except Exception:
        # 브로커 연결 끊김 등으로 명령을 내보내지 못한 경우: 기록을 "failed"로 남기고 호출한 쪽에 알립니다.
        state_store.update_command(command.commandId, status="failed")
        raise

    record = state_store.update_command(command.commandId, status="sent") or record
    return record


def on_ack_received(device_id: str, ack: AckReport) -> None:
    """가전이 ack 토픽으로 보고한 명령 처리 결과를 CommandRecord에 반영합니다."""
    result_to_status = {
        "applied": "acked",
        "rejected": "rejected",
        "failed": "failed",
    }
    new_status = result_to_status.get(ack.result, "failed")

    record = state_store.update_command(ack.commandId, status=new_status, ackedAt=ack.appliedAt)
    if record is None:
        logger.warning("알 수 없는 commandId(%s)에 대한 ack 수신 (device=%s)", ack.commandId, device_id)
        return

    ws_hub.broadcast_threadsafe(
        "command.result",
        {
            "deviceId": device_id,
            "commandId": record.commandId,
            "status": record.status,
            "result": ack.result,
            "appliedAt": ack.appliedAt,
        },
    )
