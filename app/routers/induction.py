"""
대시보드(프론트엔드)나 다른 백엔드 서비스가 호출할 REST API입니다.

주의: 가전 자체는 이 REST API를 호출하지 않습니다! 가전은 MQTT로만 통신합니다.
      (mqtt_client.py가 그 부분을 담당합니다)
이 라우터는 어디까지나 "사람/대시보드가 인덕션 상태를 보고, 제어 명령을 내리기 위한 창구"입니다.
"""

import logging

from fastapi import APIRouter, HTTPException, status

from app.config import settings
from app.mqtt_client import publish_command
from app.rules import build_control_command, validate_control_request
from app.schemas import ControlRequest, ControlResult, InductionStateReport
from app.state_store import get_last_sent_command, get_latest_state, save_last_sent_command

logger = logging.getLogger("induction.router")

router = APIRouter(prefix="/induction", tags=["induction"])


@router.get("/{device_id}/state", response_model=InductionStateReport)
def read_state(device_id: str) -> InductionStateReport:
    """가전이 마지막으로 보고한 상태를 조회합니다. (MQTT로 받아 메모리에 저장해둔 값)"""
    state = get_latest_state(device_id)
    if state is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                f"'{device_id}' 가전의 상태를 아직 받지 못했습니다. "
                "가전(또는 시뮬레이터)이 MQTT로 상태를 최소 1번은 publish해야 조회할 수 있습니다."
            ),
        )
    return state


@router.post("/{device_id}/control", response_model=ControlResult)
def send_control(device_id: str, request: ControlRequest) -> ControlResult:
    """
    인덕션에 제어 명령을 내립니다.

    흐름:
    1) 현재 캐시된 상태를 기준으로 안전 규칙(overheat 등)을 검사합니다.
    2) 문제가 없으면 command_id/timestamp를 채운 ControlCommand를 만듭니다.
    3) MQTT command 토픽으로 publish합니다. (가전이 이 토픽을 구독하고 있다가 실행)
    4) 이후 가전이 다시 상태를 publish할 때 last_control.command_id가
       이번에 발급한 command_id와 같은 값으로 돌아오는지 보면 "명령이 실제로 적용됐는지" 확인할 수 있습니다.
    """
    current_state = get_latest_state(device_id)

    errors = validate_control_request(current_state, request)
    if errors:
        return ControlResult(accepted=False, command=None, rejected_reasons=errors)

    command = build_control_command(request)

    # exclude_none=True: 명세서 규칙 "제어할 필요 없는 항목은 JSON에 포함하지 않는다"를 지키기 위함
    payload = command.model_dump(exclude_none=True)
    publish_command(device_id, payload)

    save_last_sent_command(device_id, command)

    return ControlResult(accepted=True, command=command, rejected_reasons=[])


@router.get("/{device_id}/last-command")
def read_last_command(device_id: str):
    """디버깅/확인용: 우리 서버가 이 가전에 마지막으로 보낸 명령이 무엇이었는지."""
    command = get_last_sent_command(device_id)
    if command is None:
        raise HTTPException(status_code=404, detail="아직 이 가전에 보낸 명령이 없습니다.")
    return command
