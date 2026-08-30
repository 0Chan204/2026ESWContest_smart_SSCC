"""
하드웨어 팀이 준 <인덕션 가전 데이터 명세>를 그대로 코드로 옮긴 파일입니다.

Pydantic이 처음이라면 이렇게 이해하면 됩니다:
- Pydantic 모델 = "이 JSON은 이런 필드들을 가지고 있어야 한다"를 정의한 설계도
- FastAPI는 이 설계도를 보고 자동으로 "들어온 JSON이 규격에 맞는지" 검사해줍니다.
  (필드가 없거나, 타입이 틀리거나, 정해진 값 목록에 없는 문자열이 오면 자동으로 에러를 냅니다)
- 그래서 우리가 직접 if문으로 "state가 on,off,overheat 중 하나인가?" 같은 걸
  검사하는 코드를 안 짜도 됩니다. 명세서를 이 파일에 옮겨 적기만 하면 검증은 공짜로 따라옵니다.
"""

from typing import Literal, Optional
from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# 1. 가전 상태 데이터 (가전 -> 서버, 명세서 2번 "가전 상태 정보 POST")
# ---------------------------------------------------------------------------

class ElementState(BaseModel):
    """화구 1개의 현재 상태. element_1, element_2 둘 다 이 구조를 그대로 씁니다."""

    state: Literal["on", "off", "overheat"]
    temp: float = Field(..., description="화구 온도, 단위 섭씨(℃)")
    level: int = Field(..., ge=0, le=9, description="화구 화력, 0~9")


class LastControl(BaseModel):
    """가장 최근에 이 상태를 바꾼 주체가 누구였는지."""

    publisher: Literal["user", "system", "api"]
    command_id: Optional[str] = None


class InductionStateReport(BaseModel):
    """
    인덕션이 MQTT state 토픽으로 publish하는 전체 메시지 (= 명세서 2번 예시 그대로).

    예)
    {
      "timestamp": "2026-08-23T13:37:21+09:00",
      "element_1": {"state": "on", "temp": 92.38, "level": 5},
      "element_2": {"state": "off", "temp": 30.52, "level": 0},
      "last_control": {"publisher": "api", "command_id": "cmd-20260823-000124"},
      "alarm": "off"
    }
    """

    timestamp: str  # 가전이 이 상태를 "생성한" 시각 (서버 수신 시각 아님, 명세서 4.1 참고)
    element_1: ElementState
    element_2: ElementState
    last_control: LastControl
    alarm: Literal["on", "off"]


# ---------------------------------------------------------------------------
# 2. 가전 제어 데이터 (서버 -> 가전, 명세서 3번 "가전 제어 신호 GET")
# ---------------------------------------------------------------------------

class ElementControl(BaseModel):
    """
    제어할 화구 1개에 대한 명령.

    명세서 규칙: "제어할 필요가 없는 항목은 JSON에 포함하지 않는다" 이므로
    state, level 모두 Optional로 두고, 둘 다 None이면 아예 이 필드 자체를
    응답/발행 JSON에서 빼버리는 방식(exclude_none)을 씁니다. (routers에서 처리)
    """

    state: Optional[Literal["control_on", "control_off"]] = None
    level: Optional[int] = Field(default=None, ge=1, le=9, description="화력 변경 시 1~9만 사용 (권장 규칙)")


class ControlCommand(BaseModel):
    """
    실제로 MQTT command 토픽에 publish되는 전체 메시지 (= 명세서 3번 예시 그대로).
    command_id, timestamp는 서버(우리 백엔드)가 생성해서 채워 넣습니다.
    """

    command_id: str
    timestamp: str
    element_1: Optional[ElementControl] = None
    element_2: Optional[ElementControl] = None
    alarm: Optional[Literal["control_on", "control_off"]] = None


class ControlRequest(BaseModel):
    """
    대시보드/다른 백엔드 로직이 "이렇게 제어해줘"라고 우리 FastAPI에 요청할 때 쓰는 입력 스키마.
    ControlCommand와 거의 같지만 command_id, timestamp는 클라이언트가 정하는 게 아니라
    서버가 발급해주는 것이므로 여기에는 없습니다.
    """

    element_1: Optional[ElementControl] = None
    element_2: Optional[ElementControl] = None
    alarm: Optional[Literal["control_on", "control_off"]] = None


class ControlResult(BaseModel):
    """POST /induction/{device_id}/control 요청에 대한 응답 형태."""

    accepted: bool
    command: Optional[ControlCommand] = None
    rejected_reasons: list[str] = Field(default_factory=list)
