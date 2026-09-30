"""
v0.2 API 명세(프론트/임베디드 팀 합의 반영)를 코드로 옮긴 파일입니다.

주요 변경점 (기존 v0.1 대비):
- 화구 2개(element_1/2 고정 키) -> 화구 1개, burners[] 배열 구조
- 필드명 snake_case -> camelCase (프론트 명세 기준)
- state(on/off/overheat) -> deviceState(off/on/overheated/cooling)
- 명령 처리 확인: last_control 간접 확인 + 별도 ack 메시지(팀 확정안)
- 안전 이벤트 / 조리 세션 / 부재중 정책 / 실시간 스트림 스키마 추가
"""

from typing import Literal, Optional
from pydantic import BaseModel, Field

DeviceState = Literal["off", "on", "overheated", "cooling"]


# ---------------------------------------------------------------------------
# 1. 가전 <-> 서버 (MQTT로 주고받는 메시지)
# ---------------------------------------------------------------------------

class LastControl(BaseModel):
    """가장 최근에 이 화구 상태를 바꾼 주체. publisher가 user/system인 경우는
    서버가 명령을 보낸 게 아니므로 ack로는 확인이 안 되고, 이 필드로만 알 수 있다."""

    publisher: Literal["user", "system", "api"]
    commandId: Optional[str] = None


class BurnerTelemetry(BaseModel):
    """화구 1개의 현재 상태. 화구가 1개뿐이라도 향후 확장을 고려해 배열 원소로 관리."""

    burnerId: str
    deviceState: DeviceState
    level: int = Field(..., ge=0, le=9)
    temperature: float = Field(..., description="단위 섭씨(℃)")
    activeSec: int = Field(default=0, ge=0, description="이번 조리(on 유지) 누적 사용 시간(초)")


class TelemetryReport(BaseModel):
    """
    가전이 MQTT state 토픽으로 publish하는 전체 메시지.
    발행 주기: 3초 + 상태 변경 발생 시(명령 적용/사용자 조작/과열 등) 즉시 추가 발행.
    """

    reportedAt: str
    burners: list[BurnerTelemetry]
    lastControl: LastControl
    alarm: Literal["on", "off"]


class AckReport(BaseModel):
    """가전이 MQTT ack 토픽으로 명령 처리 결과를 보고하는 메시지 (팀 확정: 별도 ack 유지)."""

    commandId: str
    result: Literal["applied", "rejected", "failed"]
    appliedAt: str
    burnerState: Optional[BurnerTelemetry] = None


class ControlCommandOut(BaseModel):
    """서버 -> 가전, MQTT command 토픽에 publish되는 실제 메시지."""

    commandId: str
    issuedAt: str
    burnerId: str
    type: Literal["turn_on", "turn_off", "set_level"]
    level: Optional[int] = Field(default=None, ge=1, le=9)


# ---------------------------------------------------------------------------
# 2. 프론트 -> 서버 (화구 제어 / 명령 조회)
# ---------------------------------------------------------------------------

class BurnerCommandRequest(BaseModel):
    type: Literal["turn_on", "turn_off", "set_level"]
    level: Optional[int] = Field(default=None, ge=1, le=9)


class CommandAccepted(BaseModel):
    commandId: str
    status: Literal["pending"] = "pending"
    issuedAt: str


class CommandRecord(BaseModel):
    """POST 화구 제어 요청 하나의 전체 생애주기를 추적하는 내부/조회용 레코드."""

    commandId: str
    status: Literal["pending", "sent", "acked", "rejected", "failed", "timeout"]
    type: Literal["turn_on", "turn_off", "set_level"]
    level: Optional[int] = None
    actor: Literal["user", "system"]
    reason: Optional[str] = None
    issuedAt: str
    ackedAt: Optional[str] = None


# ---------------------------------------------------------------------------
# 3. AI 재실 판단 모델 -> 서버
# ---------------------------------------------------------------------------

class PresenceReport(BaseModel):
    room: str
    zone: Literal["kitchen", "near", "far", "unknown"]
    present: bool
    absentSec: int = Field(default=0, ge=0)
    confidence: float = Field(..., ge=0.0, le=1.0)
    observedAt: str
    modelVersion: str


class PresenceAccepted(BaseModel):
    accepted: bool
    safetyPhase: str
    triggeredEventId: Optional[str] = None


# ---------------------------------------------------------------------------
# 4. 안전 이벤트
# ---------------------------------------------------------------------------

SafetyEventType = Literal[
    "cooking_started",
    "absence_detected",
    "auto_power_reduced",
    "auto_power_off",
    "overheat_detected",
    "command_blocked",
    "overheat_cleared",
    "user_returned",
    "cooking_ended",
]
SafetyEventSeverity = Literal["info", "warning", "danger"]


class SafetyEvent(BaseModel):
    eventId: str
    type: SafetyEventType
    severity: SafetyEventSeverity
    occurredAt: str
    room: str
    sessionId: Optional[str] = None
    temperature: Optional[float] = None
    trigger: Optional[str] = None
    action: Optional[str] = None
    reasoning: Optional[str] = None


class SafetyEventListResponse(BaseModel):
    items: list[SafetyEvent]
    page: int
    size: int
    total: int


class SafetyEventFeedback(BaseModel):
    verdict: Literal["approved", "rejected"]
    comment: Optional[str] = None


class SafetyEventFeedbackResult(BaseModel):
    eventId: str
    verdict: Literal["approved", "rejected"]
    submittedAt: str


# ---------------------------------------------------------------------------
# 5. 조리 세션
# ---------------------------------------------------------------------------

class SessionTimelineEntry(BaseModel):
    at: str
    type: str
    summary: str


class SessionRecord(BaseModel):
    sessionId: str
    startedAt: str
    endedAt: Optional[str] = None
    status: Literal["active", "ended"]
    peakTemperature: float
    timeline: list[SessionTimelineEntry] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# 6. 부재중 안전 정책 (코드에 안 박고 API로 분리, 재배포 없이 튜닝)
# ---------------------------------------------------------------------------

class KitchenAbsencePolicy(BaseModel):
    watchAfterSec: int
    reduceAfterSec: int
    offAfterSec: int
    reduceToLevel: int = Field(..., ge=0, le=9)
    minConfidence: float = Field(..., ge=0.0, le=1.0)
    nearZoneMultiplier: float
    overheatEnterC: float
    overheatExitC: float
    heartbeatTimeoutSec: int


# ---------------------------------------------------------------------------
# 7. 스냅샷 / 실시간 스트림
# ---------------------------------------------------------------------------

class KitchenRoomSnapshot(BaseModel):
    presence: Optional[PresenceReport] = None
    environment: dict = Field(default_factory=dict)
    safetyPhase: str = "normal"


class ApplianceSnapshot(BaseModel):
    deviceId: str
    online: bool
    burners: list[BurnerTelemetry] = Field(default_factory=list)
    lastControl: Optional[LastControl] = None


class SnapshotResponse(BaseModel):
    serverTime: str
    session: Optional[SessionRecord] = None
    rooms: dict[str, KitchenRoomSnapshot]
    appliances: list[ApplianceSnapshot]
    activeIncident: Optional[SafetyEvent] = None


class StreamEnvelope(BaseModel):
    """WebSocket /stream 으로 나가는 모든 메시지가 공통으로 따르는 봉투 형식."""

    event: str
    at: str
    data: dict
