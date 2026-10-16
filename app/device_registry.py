"""
집 안 가전 목록과 MQTT 토픽 규칙을 담당하는 모듈입니다. (v0.3)

가전 종류(type):
- stove          인덕션. 기존 코드(app/device_service.py, commands_service.py)가 그대로 처리합니다.
- light          전등. on / off / blink(깜빡임)
- water_purifier 정수기. dispense(출수)

MQTT 토픽은 모든 가전이 같은 규칙을 따릅니다.
    home/{구역}/{종류 토픽 이름}/{deviceId}/{state | command | ack}
예) home/room/light/light-01/command,  home/kitchen/water_purifier/water-01/state
인덕션은 기존 토픽(home/kitchen/induction/induction-01/...)을 그대로 씁니다.
"""

import json
import logging
from dataclasses import dataclass
from typing import Optional

from app.config import settings

logger = logging.getLogger("induction.registry")

STOVE = "stove"
LIGHT = "light"
WATER_PURIFIER = "water_purifier"
HOME_DEVICE_TYPES = (LIGHT, WATER_PURIFIER)

# 가전 종류 -> MQTT 토픽에 들어가는 이름
TOPIC_SEGMENT = {STOVE: "induction", LIGHT: "light", WATER_PURIFIER: "water_purifier"}
_SEGMENT_TO_TYPE = {segment: device_type for device_type, segment in TOPIC_SEGMENT.items()}

# 시연용 기본 구성 (팀 결정: 전등은 1개만, 나중에 늘릴 수 있음)
DEFAULT_HOME_DEVICES = [
    {"deviceId": "light-01", "type": LIGHT, "room": "room"},
    {"deviceId": "water-01", "type": WATER_PURIFIER, "room": "kitchen"},
]


@dataclass(frozen=True)
class Device:
    deviceId: str
    type: str
    room: str


def _home_devices() -> list[Device]:
    raw = settings.HOMEVIS_DEVICES.strip()
    entries = DEFAULT_HOME_DEVICES
    if raw:
        try:
            entries = json.loads(raw)
        except json.JSONDecodeError:
            logger.error("HOMEVIS_DEVICES 값이 올바른 JSON이 아니라 기본 가전 목록을 사용합니다.")
            entries = DEFAULT_HOME_DEVICES

    devices: list[Device] = []
    for entry in entries:
        device_type = entry.get("type")
        if device_type not in HOME_DEVICE_TYPES:
            logger.error("알 수 없는 가전 종류라 목록에서 제외합니다: %s", entry)
            continue
        devices.append(Device(deviceId=entry["deviceId"], type=device_type, room=entry.get("room", "home")))
    return devices


def list_devices() -> list[Device]:
    """인덕션 + 전등·정수기 전체 목록"""
    stove = Device(deviceId=settings.INDUCTION_DEVICE_ID, type=STOVE, room=settings.KITCHEN_ROOM)
    return [stove, *_home_devices()]


def get_device(device_id: str) -> Optional[Device]:
    return next((d for d in list_devices() if d.deviceId == device_id), None)


def find_device(device_type: str, room: Optional[str] = None) -> Optional[Device]:
    """deviceId를 모를 때: 같은 구역의 그 종류 가전을 먼저, 없으면 그 종류의 첫 번째 가전을 돌려줍니다."""
    candidates = [d for d in list_devices() if d.type == device_type]
    if room is not None:
        same_room = [d for d in candidates if d.room == room]
        if same_room:
            return same_room[0]
    return candidates[0] if candidates else None


def topic(device: Device, kind: str) -> str:
    """kind: state / command / ack"""
    if device.type == STOVE:
        return {
            "state": settings.state_topic(device.deviceId),
            "command": settings.command_topic(device.deviceId),
            "ack": settings.ack_topic(device.deviceId),
        }[kind]
    return f"home/{device.room}/{TOPIC_SEGMENT[device.type]}/{device.deviceId}/{kind}"


def home_device_subscriptions() -> list[str]:
    """서버가 구독할 전등·정수기 토픽 (구역과 deviceId는 와일드카드)"""
    return [f"home/+/{TOPIC_SEGMENT[t]}/+/{kind}" for t in HOME_DEVICE_TYPES for kind in ("state", "ack")]


def parse_topic(mqtt_topic: str) -> Optional[tuple[str, str, str]]:
    """'home/room/light/light-01/state' -> ('light', 'light-01', 'state'). 규칙에 안 맞으면 None"""
    parts = mqtt_topic.split("/")
    if len(parts) != 5 or parts[0] != "home":
        return None
    device_type = _SEGMENT_TO_TYPE.get(parts[2])
    if device_type is None:
        return None
    return device_type, parts[3], parts[4]
