"""
가전으로부터 MQTT로 올라온 "가장 최근 상태"를 메모리에 잠깐 보관해두는 곳입니다.

지금 단계에서는 DB(MariaDB/MongoDB) 연동 전이라, 서버가 꺼지면 사라지는
간단한 파이썬 딕셔너리로 시작합니다. 나중에 DB를 붙일 때는
get_latest_state / save_latest_state 두 함수의 "내부 구현"만 DB 호출로
바꾸면 되고, 이 함수들을 호출하는 쪽(routers, mqtt_client)은 그대로 둬도 됩니다.
이렇게 "저장소 접근"을 함수 뒤로 숨겨두는 걸 흔히 리포지토리 패턴이라고 부릅니다.
"""

import threading
from typing import Optional

from app.schemas import InductionStateReport, ControlCommand

# device_id -> 가장 최근 상태 보고
_latest_state: dict[str, InductionStateReport] = {}

# device_id -> 가장 최근에 우리가 발행한 제어 명령 (이력 확인/디버깅용)
_last_sent_command: dict[str, ControlCommand] = {}

# 여러 요청이 동시에 들어와도 안전하게 읽고 쓰기 위한 잠금장치
_lock = threading.Lock()


def save_latest_state(device_id: str, state: InductionStateReport) -> None:
    with _lock:
        _latest_state[device_id] = state


def get_latest_state(device_id: str) -> Optional[InductionStateReport]:
    with _lock:
        return _latest_state.get(device_id)


def save_last_sent_command(device_id: str, command: ControlCommand) -> None:
    with _lock:
        _last_sent_command[device_id] = command


def get_last_sent_command(device_id: str) -> Optional[ControlCommand]:
    with _lock:
        return _last_sent_command.get(device_id)
