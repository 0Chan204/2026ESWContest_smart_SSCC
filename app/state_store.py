"""
서버가 메모리에 들고 있는 모든 상태를 모아둔 저장소입니다.

DB(MariaDB/MongoDB) 연동 전이라 전부 파이썬 dict/list로 시작합니다.
나중에 DB를 붙일 때는 이 파일의 함수 "내부 구현"만 바꾸면 되고,
호출하는 쪽(routers, services)은 그대로 둬도 됩니다. (리포지토리 패턴)

v0.2.1 추가: 보호자 연락처(1명), 낙상 사건(FallIncident) + 확인 토큰, 낙상 안전 정책.
"""

import threading
from datetime import datetime, timezone
from typing import Optional

from app.config import settings
from app.schemas import (
    TelemetryReport,
    CommandRecord,
    SafetyEvent,
    SessionRecord,
    KitchenAbsencePolicy,
    PresenceReport,
    GuardianContact,
    UserContact,
    FallIncident,
    FallPolicy,
)

_lock = threading.Lock()

# --- 가전 텔레메트리 ---
_latest_telemetry: dict[str, TelemetryReport] = {}
_last_seen_at: dict[str, datetime] = {}

# --- 제어 명령 ---
_commands: dict[str, CommandRecord] = {}
_device_command_ids: dict[str, list[str]] = {}

# --- 안전 이벤트 (발생 순서 유지를 위해 리스트도 같이 관리) ---
_safety_events: dict[str, SafetyEvent] = {}
_safety_event_order: list[str] = []

# --- 조리 세션 ---
_sessions: dict[str, SessionRecord] = {}
_active_session_by_device: dict[str, str] = {}

# --- 재실 판단 ---
_presence_by_room: dict[str, PresenceReport] = {}
# room -> 이미 처리한 부재 단계(None/"watch"/"reduce"/"off"), 중복 조치 방지용
_absence_stage_by_room: dict[str, Optional[str]] = {}

# --- 부재중 안전 정책 (GET/PUT /policies/kitchen-absence) ---
_policy = KitchenAbsencePolicy(**settings.DEFAULT_POLICY)

# --- 보호자 연락처 (GET/PUT /guardian, 현재는 1명만 지원) ---
_guardian: Optional[GuardianContact] = None

# --- 사용자(거주자 본인) 연락처 (GET/PUT /user) ---
_user: Optional[UserContact] = None

# --- 낙상 사건 (incidentId -> FallIncident / 확인용 토큰) ---
_fall_incidents: dict[str, FallIncident] = {}
_fall_tokens: dict[str, str] = {}

# --- 낙상 안전 정책 (GET/PUT /policies/fall-safety) ---
_fall_policy = FallPolicy(**settings.DEFAULT_FALL_POLICY)


# ---------------------------------------------------------------------------
# 텔레메트리
# ---------------------------------------------------------------------------

def save_telemetry(device_id: str, report: TelemetryReport) -> None:
    with _lock:
        _latest_telemetry[device_id] = report
        _last_seen_at[device_id] = datetime.now(timezone.utc)


def get_telemetry(device_id: str) -> Optional[TelemetryReport]:
    with _lock:
        return _latest_telemetry.get(device_id)


def get_last_seen_at(device_id: str) -> Optional[datetime]:
    with _lock:
        return _last_seen_at.get(device_id)


def is_online(device_id: str) -> bool:
    """별도 heartbeat 없이, 마지막 telemetry 수신 후 policy.heartbeatTimeoutSec가
    지났는지로 온/오프라인을 판정합니다 (팀 결정: 3번 안)."""
    seen = get_last_seen_at(device_id)
    if seen is None:
        return False
    elapsed = (datetime.now(timezone.utc) - seen).total_seconds()
    return elapsed <= get_policy().heartbeatTimeoutSec


def all_known_device_ids() -> list[str]:
    with _lock:
        return list(_latest_telemetry.keys())


# ---------------------------------------------------------------------------
# 제어 명령
# ---------------------------------------------------------------------------

def save_command(record: CommandRecord) -> None:
    with _lock:
        _commands[record.commandId] = record
        _device_command_ids.setdefault(record.commandId, [])


def get_command(command_id: str) -> Optional[CommandRecord]:
    with _lock:
        return _commands.get(command_id)


def update_command(command_id: str, **changes) -> Optional[CommandRecord]:
    with _lock:
        record = _commands.get(command_id)
        if record is None:
            return None
        updated = record.model_copy(update=changes)
        _commands[command_id] = updated
        return updated


# ---------------------------------------------------------------------------
# 안전 이벤트
# ---------------------------------------------------------------------------

def save_safety_event(event: SafetyEvent) -> None:
    with _lock:
        _safety_events[event.eventId] = event
        _safety_event_order.append(event.eventId)


def get_safety_event(event_id: str) -> Optional[SafetyEvent]:
    with _lock:
        return _safety_events.get(event_id)


def list_safety_events(
    room: Optional[str] = None,
    session_id: Optional[str] = None,
    type_: Optional[str] = None,
    after_event_id: Optional[str] = None,
) -> list[SafetyEvent]:
    with _lock:
        ordered = [_safety_events[eid] for eid in _safety_event_order if eid in _safety_events]

    if after_event_id is not None:
        anchor = next((e for e in ordered if e.eventId == after_event_id), None)
        if anchor is not None:
            ordered = [e for e in ordered if e.occurredAt > anchor.occurredAt]

    if room is not None:
        ordered = [e for e in ordered if e.room == room]
    if session_id is not None:
        ordered = [e for e in ordered if e.sessionId == session_id]
    if type_ is not None:
        ordered = [e for e in ordered if e.type == type_]

    return ordered


def update_safety_event(event_id: str, **changes) -> Optional[SafetyEvent]:
    with _lock:
        event = _safety_events.get(event_id)
        if event is None:
            return None
        updated = event.model_copy(update=changes)
        _safety_events[event_id] = updated
        return updated


# ---------------------------------------------------------------------------
# 조리 세션
# ---------------------------------------------------------------------------

def save_session(record: SessionRecord) -> None:
    with _lock:
        _sessions[record.sessionId] = record


def get_session(session_id: str) -> Optional[SessionRecord]:
    with _lock:
        return _sessions.get(session_id)


def get_active_session_id(device_id: str) -> Optional[str]:
    with _lock:
        return _active_session_by_device.get(device_id)


def set_active_session_id(device_id: str, session_id: Optional[str]) -> None:
    with _lock:
        if session_id is None:
            _active_session_by_device.pop(device_id, None)
        else:
            _active_session_by_device[device_id] = session_id


# ---------------------------------------------------------------------------
# 재실 판단
# ---------------------------------------------------------------------------

def save_presence(report: PresenceReport) -> None:
    with _lock:
        _presence_by_room[report.room] = report


def get_presence(room: str) -> Optional[PresenceReport]:
    with _lock:
        return _presence_by_room.get(room)


def get_absence_stage(room: str) -> Optional[str]:
    with _lock:
        return _absence_stage_by_room.get(room)


def set_absence_stage(room: str, stage: Optional[str]) -> None:
    with _lock:
        _absence_stage_by_room[room] = stage


# ---------------------------------------------------------------------------
# 부재중 안전 정책
# ---------------------------------------------------------------------------

def get_policy() -> KitchenAbsencePolicy:
    with _lock:
        return _policy


def set_policy(policy: KitchenAbsencePolicy) -> None:
    global _policy
    with _lock:
        _policy = policy


# ---------------------------------------------------------------------------
# 보호자 연락처 (낙상 사고 안전 기능)
# ---------------------------------------------------------------------------

def get_guardian() -> Optional[GuardianContact]:
    with _lock:
        return _guardian


def set_guardian(contact: GuardianContact) -> None:
    global _guardian
    with _lock:
        _guardian = contact


def get_user() -> Optional[UserContact]:
    with _lock:
        return _user


def set_user(contact: UserContact) -> None:
    global _user
    with _lock:
        _user = contact


# ---------------------------------------------------------------------------
# 낙상 사건 (낙상 사고 안전 기능)
# ---------------------------------------------------------------------------

def save_fall_incident(incident: FallIncident, token: str) -> None:
    with _lock:
        _fall_incidents[incident.incidentId] = incident
        _fall_tokens[incident.incidentId] = token


def get_fall_incident(incident_id: str) -> Optional[FallIncident]:
    with _lock:
        return _fall_incidents.get(incident_id)


def update_fall_incident(incident_id: str, **changes) -> Optional[FallIncident]:
    with _lock:
        incident = _fall_incidents.get(incident_id)
        if incident is None:
            return None
        updated = incident.model_copy(update=changes)
        _fall_incidents[incident_id] = updated
        return updated


def get_fall_token(incident_id: str) -> Optional[str]:
    """SMS 링크에 담긴 token과 대조해서 확인 페이지 요청이 유효한지 검증하는 데 사용."""
    with _lock:
        return _fall_tokens.get(incident_id)


def get_fall_policy() -> FallPolicy:
    with _lock:
        return _fall_policy


def set_fall_policy(policy: FallPolicy) -> None:
    global _fall_policy
    with _lock:
        _fall_policy = policy
