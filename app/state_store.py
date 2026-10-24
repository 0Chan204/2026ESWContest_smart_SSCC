"""
서버의 모든 데이터를 읽고 쓰는 저장소입니다. (리포지토리 패턴)

호출하는 쪽(routers, services)은 여기 있는 함수만 사용하고, 데이터가 실제로
어디에 저장되는지는 몰라도 됩니다.

저장 방식:
- 읽기: 항상 서버 메모리(아래 dict들)에서 읽습니다.
- 쓰기: 메모리에 반영한 뒤, 같은 내용을 MongoDB에도 저장합니다 (app/db.py의 큐 사용).
- 시작: load_from_db()가 MongoDB의 내용을 메모리로 불러옵니다. -> 재시작해도 데이터 유지

MongoDB가 연결되지 않은 경우(MONGODB_URI 없음, 접속 실패)에는 메모리로만 동작합니다.
컬렉션 구조는 docs/DB.md 에 정리되어 있습니다.
"""

import logging
import threading
from collections import deque
from datetime import datetime, timezone
from typing import Optional

from app import db
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
    SmsLog,
    AiDecisionRecord,
    SensingResult,
    VoiceCommand,
    WeatherSnapshot,
)

logger = logging.getLogger("induction.store")

_lock = threading.Lock()

# 서버 시작 시 DB에서 메모리로 불러오는 최대 개수 (오래된 것은 DB에만 남습니다)
_LOAD_LIMIT_EVENTS = 1000
_LOAD_LIMIT_COMMANDS = 500
_LOAD_LIMIT_SESSIONS = 200
_LOAD_LIMIT_FALL_INCIDENTS = 200
_LOAD_LIMIT_SMS_LOGS = 200
_LOAD_LIMIT_AI_DECISIONS = 500
_LOAD_LIMIT_VOICE_COMMANDS = 500
# 최종 재실 판단 결과: 메모리에 최근 N건만 둡니다 (1초마다 오면 약 1시간 20분). 그 이전은 DB에만 남습니다.
SENSING_RESULT_MEMORY_LIMIT = 5000

# --- 가전 텔레메트리 ---
_latest_telemetry: dict[str, TelemetryReport] = {}
_last_seen_at: dict[str, datetime] = {}

# --- 제어 명령 ---
_commands: dict[str, CommandRecord] = {}

# --- 안전 이벤트 (발생 순서 유지를 위해 리스트와 순번도 같이 관리) ---
_safety_events: dict[str, SafetyEvent] = {}
_safety_event_order: list[str] = []
_safety_event_seq: dict[str, int] = {}
_next_event_seq = 1

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

# --- 문자 발송 이력 (오래된 순서대로) ---
_sms_logs: list[SmsLog] = []
_next_sms_seq = 1

# --- v0.3: 전등·정수기 최신 상태 (deviceId -> {"type", "state"}) ---
_device_states: dict[str, dict] = {}
_device_last_seen: dict[str, datetime] = {}

# --- v0.3: HomeVIS가 끄거나 낮추기 직전의 인덕션 화력 (deviceId -> level, restore_power용) ---
_restore_levels: dict[str, int] = {}

# --- v0.5: 절전(power_saving)으로 밝기를 낮춘 전등 (power_saving_end 때 이 전등만 100%로 되돌림) ---
_power_saving_lights: set[str] = set()

# --- v0.3.2: 마지막으로 받아 둔 날씨 (인터넷이 끊겨도 안내할 수 있도록 DB에도 저장) ---
_weather: Optional[WeatherSnapshot] = None

# --- v0.4: 최종 재실 판단 결과 (오래된 것부터) ---
_sensing_results: "deque[SensingResult]" = deque(maxlen=SENSING_RESULT_MEMORY_LIMIT)
_sensing_result_ids: set[str] = set()
_next_sensing_seq = 1

# --- v0.3: AI 판단 기록 ---
_ai_decisions: dict[str, AiDecisionRecord] = {}
_ai_decision_order: list[str] = []
_ai_decision_seq: dict[str, int] = {}
_next_ai_seq = 1

# --- v0.6: 음성 명령 ---
_voice_commands: dict[str, VoiceCommand] = {}
_voice_order: list[str] = []
_voice_seq: dict[str, int] = {}
_next_voice_seq = 1

_POLICY_KITCHEN_ABSENCE = "kitchen-absence"
_POLICY_FALL_SAFETY = "fall-safety"
_CONTACT_USER = "user"
_CONTACT_GUARDIAN = "guardian"
_STATE_ACTIVE_SESSIONS = "active_sessions"
_STATE_ABSENCE_STAGES = "absence_stages"
_STATE_RESTORE_LEVELS = "restore_levels"
_STATE_POWER_SAVING_LIGHTS = "power_saving_lights"
_STATE_WEATHER = "weather"


# ---------------------------------------------------------------------------
# 시작 / 초기화
# ---------------------------------------------------------------------------

def reset_memory() -> None:
    """메모리의 모든 데이터를 초기 상태로 되돌립니다. (DB는 건드리지 않음. 시작 시, 테스트에서 사용)"""
    global _policy, _fall_policy, _guardian, _user, _next_event_seq, _next_sms_seq, _next_ai_seq, _weather
    global _next_sensing_seq, _next_voice_seq
    with _lock:
        _weather = None
        _voice_order.clear()
        _next_voice_seq = 1
        _sensing_results.clear()
        _sensing_result_ids.clear()
        _next_sensing_seq = 1
        for store in (
            _latest_telemetry,
            _last_seen_at,
            _commands,
            _safety_events,
            _safety_event_seq,
            _sessions,
            _active_session_by_device,
            _presence_by_room,
            _absence_stage_by_room,
            _fall_incidents,
            _fall_tokens,
            _device_states,
            _device_last_seen,
            _restore_levels,
            _power_saving_lights,
            _ai_decisions,
            _ai_decision_seq,
            _voice_commands,
            _voice_seq,
        ):
            store.clear()
        _safety_event_order.clear()
        _sms_logs.clear()
        _ai_decision_order.clear()
        _next_event_seq = 1
        _next_sms_seq = 1
        _next_ai_seq = 1
        _policy = KitchenAbsencePolicy(**settings.DEFAULT_POLICY)
        _fall_policy = FallPolicy(**settings.DEFAULT_FALL_POLICY)
        _guardian = None
        _user = None


def _without_id(document: dict, *extra_keys: str) -> dict:
    return {k: v for k, v in document.items() if k != "_id" and k not in extra_keys}


def _as_utc(value: datetime) -> datetime:
    # MongoDB에서 읽은 날짜는 시간대 정보가 빠져 있으므로 UTC로 표시해 줍니다.
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def load_from_db() -> None:
    """서버 시작 시 1번 호출: MongoDB에 저장된 내용을 메모리로 불러옵니다."""
    global _policy, _fall_policy, _guardian, _user, _next_event_seq

    if not db.is_enabled():
        return

    reset_memory()

    def load(name: str, loader) -> None:
        # 한 종류를 불러오다 실패해도 나머지는 계속 불러옵니다.
        try:
            loader()
        except Exception:
            logger.exception("DB에서 '%s' 불러오기 실패 (해당 데이터만 빈 상태로 시작)", name)

    def load_telemetry() -> None:
        for doc in db.find_all(db.TELEMETRY_LATEST):
            device_id = doc["_id"]
            _latest_telemetry[device_id] = TelemetryReport.model_validate(doc["report"])
            _last_seen_at[device_id] = _as_utc(doc["lastSeenAt"])

    def load_commands() -> None:
        for doc in db.find_all(db.COMMANDS, sort_field="issuedAt", newest_limit=_LOAD_LIMIT_COMMANDS):
            record = CommandRecord.model_validate(_without_id(doc))
            _commands[record.commandId] = record

    def load_events() -> None:
        global _next_event_seq
        for doc in db.find_all(db.SAFETY_EVENTS, sort_field="seq", newest_limit=_LOAD_LIMIT_EVENTS):
            event = SafetyEvent.model_validate(_without_id(doc, "seq"))
            _safety_events[event.eventId] = event
            _safety_event_order.append(event.eventId)
            _safety_event_seq[event.eventId] = doc["seq"]
            _next_event_seq = max(_next_event_seq, doc["seq"] + 1)

    def load_sessions() -> None:
        for doc in db.find_all(db.SESSIONS, sort_field="startedAt", newest_limit=_LOAD_LIMIT_SESSIONS):
            record = SessionRecord.model_validate(_without_id(doc))
            _sessions[record.sessionId] = record

    def load_presence() -> None:
        for doc in db.find_all(db.PRESENCE):
            report = PresenceReport.model_validate(_without_id(doc))
            _presence_by_room[report.room] = report

    def load_policies() -> None:
        global _policy, _fall_policy
        for doc in db.find_all(db.POLICIES):
            if doc["_id"] == _POLICY_KITCHEN_ABSENCE:
                _policy = KitchenAbsencePolicy.model_validate(_without_id(doc))
            elif doc["_id"] == _POLICY_FALL_SAFETY:
                _fall_policy = FallPolicy.model_validate(_without_id(doc))

    def load_contacts() -> None:
        global _guardian, _user
        for doc in db.find_all(db.CONTACTS):
            if doc["_id"] == _CONTACT_GUARDIAN:
                _guardian = GuardianContact.model_validate(_without_id(doc))
            elif doc["_id"] == _CONTACT_USER:
                _user = UserContact.model_validate(_without_id(doc))

    def load_fall_incidents() -> None:
        for doc in db.find_all(db.FALL_INCIDENTS, sort_field="detectedAt", newest_limit=_LOAD_LIMIT_FALL_INCIDENTS):
            incident = FallIncident.model_validate(_without_id(doc, "token"))
            _fall_incidents[incident.incidentId] = incident
            _fall_tokens[incident.incidentId] = doc.get("token", "")

    def load_sms_logs() -> None:
        # 같은 초에 여러 건이 발송될 수 있어서, 시각이 아니라 일련번호(seq)로 순서를 보장합니다.
        global _next_sms_seq
        for doc in db.find_all(db.SMS_LOGS, sort_field="seq", newest_limit=_LOAD_LIMIT_SMS_LOGS):
            _sms_logs.append(SmsLog.model_validate(_without_id(doc, "seq")))
            _next_sms_seq = max(_next_sms_seq, doc["seq"] + 1)

    def load_runtime_state() -> None:
        global _weather
        for doc in db.find_all(db.RUNTIME_STATE):
            if doc["_id"] == _STATE_ACTIVE_SESSIONS:
                _active_session_by_device.update(doc.get("values", {}))
            elif doc["_id"] == _STATE_ABSENCE_STAGES:
                _absence_stage_by_room.update(doc.get("values", {}))
            elif doc["_id"] == _STATE_RESTORE_LEVELS:
                _restore_levels.update(doc.get("values", {}))
            elif doc["_id"] == _STATE_POWER_SAVING_LIGHTS:
                _power_saving_lights.update(doc.get("values", []))
            elif doc["_id"] == _STATE_WEATHER and doc.get("value"):
                _weather = WeatherSnapshot.model_validate(doc["value"])

    def load_device_states() -> None:
        for doc in db.find_all(db.DEVICE_STATES):
            device_id = doc["_id"]
            _device_states[device_id] = {"type": doc.get("type"), "state": doc.get("state", {})}
            if doc.get("lastSeenAt") is not None:
                _device_last_seen[device_id] = _as_utc(doc["lastSeenAt"])

    def load_ai_decisions() -> None:
        global _next_ai_seq
        for doc in db.find_all(db.AI_DECISIONS, sort_field="seq", newest_limit=_LOAD_LIMIT_AI_DECISIONS):
            record = AiDecisionRecord.model_validate(_without_id(doc, "seq"))
            _ai_decisions[record.decisionId] = record
            _ai_decision_order.append(record.decisionId)
            _ai_decision_seq[record.decisionId] = doc["seq"]
            _next_ai_seq = max(_next_ai_seq, doc["seq"] + 1)

    def load_sensing_results() -> None:
        global _next_sensing_seq
        docs = db.find_all(db.SENSING_RESULTS, sort_field="seq", newest_limit=SENSING_RESULT_MEMORY_LIMIT)
        for doc in docs:
            result = SensingResult.model_validate(_without_id(doc, "seq", "savedAtTime"))
            _sensing_results.append(result)
            _sensing_result_ids.add(result.resultId)
            _next_sensing_seq = max(_next_sensing_seq, doc["seq"] + 1)

    def load_voice_commands() -> None:
        global _next_voice_seq
        for doc in db.find_all(db.VOICE_COMMANDS, sort_field="seq", newest_limit=_LOAD_LIMIT_VOICE_COMMANDS):
            command = VoiceCommand.model_validate(_without_id(doc, "seq", "receivedAtTime"))
            _voice_commands[command.voiceId] = command
            _voice_order.append(command.voiceId)
            _voice_seq[command.voiceId] = doc["seq"]
            _next_voice_seq = max(_next_voice_seq, doc["seq"] + 1)

    with _lock:
        load("인덕션 상태", load_telemetry)
        load("제어 명령", load_commands)
        load("안전 이벤트", load_events)
        load("조리 세션", load_sessions)
        load("재실 판단", load_presence)
        load("정책", load_policies)
        load("연락처", load_contacts)
        load("낙상 사건", load_fall_incidents)
        load("문자 발송 이력", load_sms_logs)
        load("진행 상태", load_runtime_state)
        load("전등·정수기 상태", load_device_states)
        load("AI 판단 기록", load_ai_decisions)
        load("최종 재실 판단 결과", load_sensing_results)
        load("음성 명령", load_voice_commands)

    logger.info(
        "DB에서 불러옴: 안전 이벤트 %d건, 제어 명령 %d건, 조리 세션 %d건, 낙상 사건 %d건",
        len(_safety_events),
        len(_commands),
        len(_sessions),
        len(_fall_incidents),
    )


# ---------------------------------------------------------------------------
# 텔레메트리
# ---------------------------------------------------------------------------

def save_telemetry(device_id: str, report: TelemetryReport) -> None:
    now = datetime.now(timezone.utc)
    with _lock:
        _latest_telemetry[device_id] = report
        _last_seen_at[device_id] = now
    body = report.model_dump()
    # 최신 값 1건(재시작 후 바로 조회용) + 시간순 로그(일정 기간 후 자동 삭제)
    db.upsert(db.TELEMETRY_LATEST, device_id, {"report": body, "lastSeenAt": now})
    db.insert(db.TELEMETRY_LOGS, {"deviceId": device_id, "receivedAt": now, **body})


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
    db.upsert(db.COMMANDS, record.commandId, record.model_dump())


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
    db.upsert(db.COMMANDS, command_id, updated.model_dump())
    return updated


# ---------------------------------------------------------------------------
# 안전 이벤트
# ---------------------------------------------------------------------------

def save_safety_event(event: SafetyEvent) -> None:
    global _next_event_seq
    with _lock:
        seq = _next_event_seq
        _next_event_seq += 1
        _safety_events[event.eventId] = event
        _safety_event_order.append(event.eventId)
        _safety_event_seq[event.eventId] = seq
    db.upsert(db.SAFETY_EVENTS, event.eventId, {"seq": seq, **event.model_dump()})


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
        seq = _safety_event_seq.get(event_id, 0)
    db.upsert(db.SAFETY_EVENTS, event_id, {"seq": seq, **updated.model_dump()})
    return updated


# ---------------------------------------------------------------------------
# 조리 세션
# ---------------------------------------------------------------------------

def save_session(record: SessionRecord) -> None:
    with _lock:
        _sessions[record.sessionId] = record
    db.upsert(db.SESSIONS, record.sessionId, record.model_dump())


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
        snapshot = dict(_active_session_by_device)
    db.upsert(db.RUNTIME_STATE, _STATE_ACTIVE_SESSIONS, {"values": snapshot})


# ---------------------------------------------------------------------------
# 재실 판단
# ---------------------------------------------------------------------------

def save_presence(report: PresenceReport) -> None:
    with _lock:
        _presence_by_room[report.room] = report
    db.upsert(db.PRESENCE, report.room, report.model_dump())


def get_presence(room: str) -> Optional[PresenceReport]:
    with _lock:
        return _presence_by_room.get(room)


def get_absence_stage(room: str) -> Optional[str]:
    with _lock:
        return _absence_stage_by_room.get(room)


def set_absence_stage(room: str, stage: Optional[str]) -> None:
    with _lock:
        _absence_stage_by_room[room] = stage
        snapshot = dict(_absence_stage_by_room)
    db.upsert(db.RUNTIME_STATE, _STATE_ABSENCE_STAGES, {"values": snapshot})


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
    db.upsert(db.POLICIES, _POLICY_KITCHEN_ABSENCE, policy.model_dump())


# ---------------------------------------------------------------------------
# 사용자 / 보호자 연락처
# ---------------------------------------------------------------------------

def get_guardian() -> Optional[GuardianContact]:
    with _lock:
        return _guardian


def set_guardian(contact: GuardianContact) -> None:
    global _guardian
    with _lock:
        _guardian = contact
    db.upsert(db.CONTACTS, _CONTACT_GUARDIAN, contact.model_dump())


def get_user() -> Optional[UserContact]:
    with _lock:
        return _user


def set_user(contact: UserContact) -> None:
    global _user
    with _lock:
        _user = contact
    db.upsert(db.CONTACTS, _CONTACT_USER, contact.model_dump())


# ---------------------------------------------------------------------------
# 낙상 사건
# ---------------------------------------------------------------------------

def save_fall_incident(incident: FallIncident, token: str) -> None:
    with _lock:
        _fall_incidents[incident.incidentId] = incident
        _fall_tokens[incident.incidentId] = token
    db.upsert(db.FALL_INCIDENTS, incident.incidentId, {"token": token, **incident.model_dump()})


def get_fall_incident(incident_id: str) -> Optional[FallIncident]:
    with _lock:
        return _fall_incidents.get(incident_id)


def list_pending_fall_incidents() -> list[FallIncident]:
    """아직 보호자 응답을 기다리는 낙상 사건 목록. (재시작 후 자동 신고 타이머를 다시 걸 때 사용)"""
    with _lock:
        return [i for i in _fall_incidents.values() if i.status == "pending"]


def update_fall_incident(incident_id: str, **changes) -> Optional[FallIncident]:
    with _lock:
        incident = _fall_incidents.get(incident_id)
        if incident is None:
            return None
        updated = incident.model_copy(update=changes)
        _fall_incidents[incident_id] = updated
        token = _fall_tokens.get(incident_id, "")
    db.upsert(db.FALL_INCIDENTS, incident_id, {"token": token, **updated.model_dump()})
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
    db.upsert(db.POLICIES, _POLICY_FALL_SAFETY, policy.model_dump())


# ---------------------------------------------------------------------------
# 문자 발송 이력
# ---------------------------------------------------------------------------

def save_sms_log(log: SmsLog) -> None:
    global _next_sms_seq
    with _lock:
        seq = _next_sms_seq
        _next_sms_seq += 1
        _sms_logs.append(log)
    db.upsert(db.SMS_LOGS, log.logId, {"seq": seq, **log.model_dump()})


def list_sms_logs() -> list[SmsLog]:
    """오래된 것부터 순서대로 돌려줍니다."""
    with _lock:
        return list(_sms_logs)


# ---------------------------------------------------------------------------
# v0.3: 전등·정수기 상태
# ---------------------------------------------------------------------------

def save_device_state(device_id: str, device_type: str, state: dict) -> None:
    now = datetime.now(timezone.utc)
    with _lock:
        _device_states[device_id] = {"type": device_type, "state": state}
        _device_last_seen[device_id] = now
    db.upsert(db.DEVICE_STATES, device_id, {"type": device_type, "state": state, "lastSeenAt": now})


def get_device_state(device_id: str) -> Optional[dict]:
    """마지막으로 받은 상태 메시지(dict). 아직 없으면 None"""
    with _lock:
        entry = _device_states.get(device_id)
        return dict(entry["state"]) if entry else None


def get_device_last_seen(device_id: str) -> Optional[datetime]:
    with _lock:
        return _device_last_seen.get(device_id)


def is_device_online(device_id: str) -> bool:
    """인덕션과 같은 기준: 마지막 상태 수신 후 heartbeatTimeoutSec가 지나지 않았으면 온라인"""
    seen = get_device_last_seen(device_id)
    if seen is None:
        return False
    return (datetime.now(timezone.utc) - seen).total_seconds() <= get_policy().heartbeatTimeoutSec


# ---------------------------------------------------------------------------
# v0.3: restore_power용 이전 화력
# ---------------------------------------------------------------------------

def get_restore_level(device_id: str) -> Optional[int]:
    with _lock:
        return _restore_levels.get(device_id)


def set_restore_level(device_id: str, level: Optional[int]) -> None:
    """level=None이면 지웁니다. 값이 그대로면 DB에 다시 쓰지 않습니다."""
    with _lock:
        if _restore_levels.get(device_id) == level:
            return
        if level is None:
            _restore_levels.pop(device_id, None)
        else:
            _restore_levels[device_id] = level
        snapshot = dict(_restore_levels)
    db.upsert(db.RUNTIME_STATE, _STATE_RESTORE_LEVELS, {"values": snapshot})


# ---------------------------------------------------------------------------
# v0.5: 절전으로 밝기를 낮춘 전등
# ---------------------------------------------------------------------------

def is_power_saving_light(device_id: str) -> bool:
    with _lock:
        return device_id in _power_saving_lights


def set_power_saving_light(device_id: str, saving: bool) -> None:
    """saving=True면 절전 중으로 표시, False면 해제. 바뀐 게 없으면 DB에 다시 쓰지 않습니다."""
    with _lock:
        if (device_id in _power_saving_lights) == saving:
            return
        if saving:
            _power_saving_lights.add(device_id)
        else:
            _power_saving_lights.discard(device_id)
        snapshot = sorted(_power_saving_lights)
    db.upsert(db.RUNTIME_STATE, _STATE_POWER_SAVING_LIGHTS, {"values": snapshot})


# ---------------------------------------------------------------------------
# v0.3.2: 날씨 캐시
# ---------------------------------------------------------------------------

def get_weather() -> Optional[WeatherSnapshot]:
    with _lock:
        return _weather


def set_weather(snapshot: WeatherSnapshot) -> None:
    global _weather
    with _lock:
        _weather = snapshot
    db.upsert(db.RUNTIME_STATE, _STATE_WEATHER, {"value": snapshot.model_dump()})


# ---------------------------------------------------------------------------
# v0.3: AI 판단 기록
# ---------------------------------------------------------------------------

def save_ai_decision(record: AiDecisionRecord) -> None:
    global _next_ai_seq
    with _lock:
        seq = _ai_decision_seq.get(record.decisionId)
        if seq is None:
            seq = _next_ai_seq
            _next_ai_seq += 1
            _ai_decision_order.append(record.decisionId)
            _ai_decision_seq[record.decisionId] = seq
        _ai_decisions[record.decisionId] = record
    db.upsert(db.AI_DECISIONS, record.decisionId, {"seq": seq, **record.model_dump()})


def get_ai_decision(decision_id: str) -> Optional[AiDecisionRecord]:
    with _lock:
        return _ai_decisions.get(decision_id)


def update_ai_decision(decision_id: str, **changes) -> Optional[AiDecisionRecord]:
    with _lock:
        record = _ai_decisions.get(decision_id)
        if record is None:
            return None
        updated = record.model_copy(update=changes)
    save_ai_decision(updated)
    return updated


def list_ai_decisions() -> list[AiDecisionRecord]:
    """오래된 것부터 순서대로 돌려줍니다."""
    with _lock:
        return [_ai_decisions[d] for d in _ai_decision_order if d in _ai_decisions]


# ---------------------------------------------------------------------------
# v0.4: 최종 재실 판단 결과
# ---------------------------------------------------------------------------

def save_sensing_result(result: SensingResult) -> bool:
    """저장했으면 True, 이미 받은 resultId라 건너뛰었으면 False"""
    global _next_sensing_seq
    with _lock:
        if result.resultId in _sensing_result_ids:
            return False
        if len(_sensing_results) == _sensing_results.maxlen:
            _sensing_result_ids.discard(_sensing_results[0].resultId)
        _sensing_results.append(result)
        _sensing_result_ids.add(result.resultId)
        seq = _next_sensing_seq
        _next_sensing_seq += 1
    saved_time = datetime.fromisoformat(result.savedAt)
    db.upsert(db.SENSING_RESULTS, result.resultId, {"seq": seq, "savedAtTime": saved_time, **result.model_dump()})
    return True


def get_latest_sensing_result() -> Optional[SensingResult]:
    with _lock:
        return _sensing_results[-1] if _sensing_results else None


def list_sensing_results() -> list[SensingResult]:
    """메모리에 있는 최근 결과 (오래된 것부터)"""
    with _lock:
        return list(_sensing_results)


# ---------------------------------------------------------------------------
# v0.6: 음성 명령
# ---------------------------------------------------------------------------

def _persist_voice_command(command: VoiceCommand, seq: int) -> None:
    received = datetime.fromisoformat(command.receivedAt)
    db.upsert(db.VOICE_COMMANDS, command.voiceId, {"seq": seq, "receivedAtTime": received, **command.model_dump()})


def save_voice_command(command: VoiceCommand) -> None:
    global _next_voice_seq
    with _lock:
        seq = _voice_seq.get(command.voiceId)
        if seq is None:
            seq = _next_voice_seq
            _next_voice_seq += 1
            _voice_order.append(command.voiceId)
            _voice_seq[command.voiceId] = seq
        _voice_commands[command.voiceId] = command
    _persist_voice_command(command, seq)


def get_voice_command(voice_id: str) -> Optional[VoiceCommand]:
    with _lock:
        return _voice_commands.get(voice_id)


def transition_voice_command(voice_id: str, expected: set[str], **changes) -> Optional[VoiceCommand]:
    """현재 상태가 expected 중 하나일 때만 바꾸고 바뀐 기록을 돌려줍니다. 아니면 None.
    판정 엔진 응답·사용자 확인·시간 초과가 동시에 일어나도 한 가지만 반영되도록 합니다."""
    with _lock:
        command = _voice_commands.get(voice_id)
        if command is None or command.status not in expected:
            return None
        updated = command.model_copy(update=changes)
        _voice_commands[voice_id] = updated
        seq = _voice_seq[voice_id]
    _persist_voice_command(updated, seq)
    return updated


def list_voice_commands() -> list[VoiceCommand]:
    """오래된 것부터 순서대로 돌려줍니다."""
    with _lock:
        return [_voice_commands[v] for v in _voice_order if v in _voice_commands]
