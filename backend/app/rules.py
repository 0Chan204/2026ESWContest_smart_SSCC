"""
안전 로직을 코드로 옮긴 파일입니다.

핵심 규칙 (팀 확정):
- 화구가 overheated 상태인 경우 turn_on / set_level(화력 증가) 명령을 거부한다.
- overheated 상태에서도 turn_off 명령은 항상 허용한다.
- 이 검증은 FastAPI 라우터에서 MQTT로 명령을 내보내기 "직전"에 수행합니다.
  (서버가 1차 방어선, 가전 자체도 동일 규칙을 한 번 더 검사)
"""

import uuid
from datetime import datetime, timezone
from typing import Optional

from app.schemas import BurnerCommandRequest, ControlCommandOut, TelemetryReport


def generate_command_id() -> str:
    now = datetime.now(timezone.utc)
    return f"cmd-{now.strftime('%Y%m%d')}-{uuid.uuid4().hex[:8]}"


def current_timestamp_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def validate_burner_command(
    current_telemetry: Optional[TelemetryReport],
    burner_id: str,
    request: BurnerCommandRequest,
) -> list[str]:
    """
    현재 화구 상태를 기준으로 이 제어 요청이 안전 규칙을 어기는지 검사합니다.
    문제가 없으면 빈 리스트, 있으면 사람이 읽을 수 있는 사유 문자열 리스트를 돌려줍니다.

    current_telemetry가 아직 없다면(=서버가 이 화구의 상태를 한 번도 못 받은 경우)
    안전하게 "판단 보류"로 보고 통과시킵니다.
    """
    if current_telemetry is None:
        return []

    burner = next((b for b in current_telemetry.burners if b.burnerId == burner_id), None)
    if burner is None or burner.deviceState != "overheated":
        return []

    if request.type == "turn_off":
        return []

    # turn_on 또는 set_level(화력 지정)은 overheated 상태에서 전부 거부
    return [
        f"'{burner_id}' 화구가 overheated(과열 잠금) 상태입니다. "
        "turn_off 외의 명령(전원 ON, 화력 지정)은 거부됩니다."
    ]


def build_control_command(burner_id: str, request: BurnerCommandRequest) -> ControlCommandOut:
    return ControlCommandOut(
        commandId=generate_command_id(),
        issuedAt=current_timestamp_iso(),
        burnerId=burner_id,
        type=request.type,
        level=request.level,
    )
