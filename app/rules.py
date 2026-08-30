"""
명세서 3번 "주요 규칙"에 있는 안전 로직을 코드로 옮긴 파일입니다.

핵심 규칙 (명세서 원문):
- 화구가 overheat 상태인 경우 control_on 또는 화력 증가 명령을 거부한다.
- overheat 상태에서도 control_off 명령은 허용한다.

이 검증은 FastAPI 라우터에서 MQTT로 명령을 내보내기 "직전"에 수행합니다.
즉, 우리 백엔드가 1차 방어선 역할을 합니다. (실제 가전 쪽에서도 자체적으로
같은 규칙을 한 번 더 검사하겠지만, 서버에서도 걸러주면 불필요한 MQTT 트래픽과
오작동 가능성을 줄일 수 있습니다.)
"""

import uuid
from datetime import datetime, timezone

from app.schemas import ControlRequest, ControlCommand, InductionStateReport

ELEMENT_FIELDS = ("element_1", "element_2")


def generate_command_id() -> str:
    """
    명세서 예시(cmd-20260823-000124)와 같은 형식의 사람이 읽기 쉬운 ID를 만듭니다.
    뒤에 붙는 8자리는 충돌 방지를 위한 임의 문자열입니다.
    """
    now = datetime.now(timezone.utc)
    return f"cmd-{now.strftime('%Y%m%d')}-{uuid.uuid4().hex[:8]}"


def current_timestamp_iso() -> str:
    """ISO 8601 형식 타임스탬프. 명세서 4.1에 나온 형식(+09:00 같은 오프셋 포함)을 맞추기 위해
    타임존 정보가 있는 datetime을 사용합니다."""
    return datetime.now().astimezone().isoformat(timespec="seconds")


def validate_control_request(
    current_state: InductionStateReport | None,
    request: ControlRequest,
) -> list[str]:
    """
    현재 가전 상태(current_state)를 기준으로 이 제어 요청이 안전 규칙을 어기는지 검사합니다.
    문제가 없으면 빈 리스트, 있으면 사람이 읽을 수 있는 사유 문자열 리스트를 돌려줍니다.

    current_state가 아직 없다면 (=서버가 시작된 후 가전으로부터 상태를 한 번도
    못 받은 경우) 안전하게 "판단 보류"로 보고, 일단 통과시킵니다.
    """
    errors: list[str] = []

    if current_state is None:
        return errors

    for field_name in ELEMENT_FIELDS:
        element_control = getattr(request, field_name)
        if element_control is None:
            continue  # 이 화구는 이번 요청에서 건드리지 않음

        element_state = getattr(current_state, field_name)
        if element_state.state != "overheat":
            continue

        wants_power_on = element_control.state == "control_on"
        wants_more_heat = element_control.level is not None and element_control.level > 0

        if wants_power_on or wants_more_heat:
            errors.append(
                f"{field_name}가 overheat(과열) 상태입니다. "
                "control_off 외의 명령(전원 ON, 화력 상향)은 거부됩니다."
            )

    return errors


def build_control_command(request: ControlRequest) -> ControlCommand:
    """검증을 통과한 ControlRequest에 command_id / timestamp를 채워 실제로
    MQTT에 실어 보낼 ControlCommand를 만듭니다."""
    return ControlCommand(
        command_id=generate_command_id(),
        timestamp=current_timestamp_iso(),
        element_1=request.element_1,
        element_2=request.element_2,
        alarm=request.alarm,
    )
