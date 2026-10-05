"""
v0.2 API 명세(프론트/임베디드 팀 합의 반영)를 코드로 옮긴 파일입니다.

주요 변경점 (기존 v0.1 대비):
- 화구 2개(element_1/2 고정 키) -> 화구 1개, burners[] 배열 구조
- 필드명 snake_case -> camelCase (프론트 명세 기준)
- state(on/off/overheat) -> deviceState(off/on/overheated/cooling)
- 명령 처리 확인: last_control 간접 확인 + 별도 ack 메시지(팀 확정안)
- 안전 이벤트 / 조리 세션 / 부재중 정책 / 실시간 스트림 스키마 추가

v0.2.1 추가 (낙상 사고 안전 기능):
- 보호자 연락처(GuardianContact), 낙상 이벤트(FallDetectedReport), 낙상 사건
  생애주기(FallIncident), 낙상 안전 정책(FallPolicy) 스키마 추가
- SafetyEventType에 fall_detected / fall_resolved / fall_reported /
  fall_auto_reported 4종 추가
"""

import re
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator

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
    # v0.2.1: 낙상 사고 안전 기능
    "fall_detected",
    "fall_resolved",
    "fall_reported",
    "fall_auto_reported",
]
SafetyEventSeverity = Literal["info", "warning", "danger"]


class SafetyEventFeedbackRecord(BaseModel):
    """안전 이벤트에 대해 사용자가 남긴 의견. 이벤트 문서 안에 함께 저장됩니다 (가장 최근 1건)."""

    verdict: Literal["approved", "rejected"]
    comment: Optional[str] = None
    submittedAt: str


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
    feedback: Optional[SafetyEventFeedbackRecord] = None


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


# ---------------------------------------------------------------------------
# 8. 낙상 사고 안전 기능 (v0.2.1 추가)
#
# 흐름: 낙상 감지 AI 모델 -> POST /safety/fall-events -> 서버가
#   (1) 인덕션 즉시 비상 전원 차단(0단계), (2) 안전 이벤트 생성 + 대시보드 알림,
#   (3) 보호자에게 SMS로 확인 링크 발송 을 동시에 수행하고 FallIncident를 만듭니다.
# 보호자가 SMS 링크(프론트가 만드는 모바일 페이지)에서 "해결" 또는 "신고"를 누르면
# 그 페이지가 POST .../resolve 또는 .../report를 호출합니다.
# 일정 시간(policy.autoReportSec) 안에 아무 응답이 없으면 서버가 자동으로 "신고" 처리합니다.
# ---------------------------------------------------------------------------

def _normalize_phone(value: str) -> str:
    """'010-1234-5678', '010 1234 5678' 처럼 들어와도 숫자만 남겨 저장합니다.
    (문자 발송 API가 숫자만 있는 번호를 요구하기 때문)"""
    digits = re.sub(r"\D", "", value)
    if not (9 <= len(digits) <= 11) or not digits.startswith("0"):
        raise ValueError("전화번호 형식이 올바르지 않습니다. 예: 01012345678 또는 010-1234-5678")
    return digits


class UserContact(BaseModel):
    """대시보드에서 등록/수정하는 사용자(거주자 본인) 연락처.
    낙상 문자는 보호자에게만 가고(팀 결정), 사용자 번호는 등록 확인 문자와 정보 표시용입니다."""

    name: str = Field(..., min_length=1)
    phone: str = Field(..., description="하이픈 유무 상관없음. 저장 시 숫자만 남깁니다.")

    _phone = field_validator("phone")(_normalize_phone)


class UserContactUpdateResult(BaseModel):
    user: UserContact
    verificationSent: bool = Field(..., description="연락처 저장 후 확인 문자 발송 성공 여부")
    message: str


class GuardianContact(BaseModel):
    """대시보드에서 등록/수정하는 보호자 연락처 (현재는 1명만 지원하기로 팀 결정).
    낙상 사고 발생 시 이 번호로 확인 링크가 담긴 문자가 발송됩니다."""

    name: str = Field(..., min_length=1)
    phone: str = Field(..., description="하이픈 유무 상관없음. 저장 시 숫자만 남깁니다.")

    _phone = field_validator("phone")(_normalize_phone)


class GuardianContactUpdateResult(BaseModel):
    guardian: GuardianContact
    verificationSent: bool = Field(..., description="연락처 저장 후 확인 문자 발송 성공 여부")
    message: str


SmsPurpose = Literal["user_verification", "guardian_verification", "fall_alert"]


class SmsLog(BaseModel):
    """문자 발송 1건의 기록. 본문은 저장하지 않습니다 (낙상 문자에는 확인 링크의 토큰이 들어 있기 때문)."""

    logId: str
    to: str
    purpose: SmsPurpose
    success: bool
    sentAt: str
    incidentId: Optional[str] = Field(default=None, description="낙상 알림 문자인 경우 해당 사건 ID")


class SmsLogListResponse(BaseModel):
    items: list[SmsLog]
    total: int


class FallDetectedReport(BaseModel):
    """낙상 감지 AI 모델 -> 서버. 재실 판단 모델(PresenceReport)과 동일한 패턴으로,
    모델은 '감지 사실'만 보고하고 조치(차단/알림/SMS)는 전적으로 서버가 결정합니다."""

    room: str
    confidence: float = Field(..., ge=0.0, le=1.0)
    observedAt: str
    modelVersion: str


FallIncidentStatus = Literal["pending", "resolved", "reported", "auto_reported"]


class FallIncident(BaseModel):
    """낙상 사건 하나의 전체 생애주기를 추적하는 레코드."""

    incidentId: str
    room: str
    status: FallIncidentStatus
    detectedAt: str
    confidence: float
    confirmUrl: str = Field(..., description="SMS로 발송되는, 프론트의 모바일 확인 페이지 링크")
    autoReportAt: str = Field(..., description="이 시각까지 응답이 없으면 자동으로 신고 처리됨")
    eventId: Optional[str] = None
    resolvedAt: Optional[str] = None
    reportedAt: Optional[str] = None


class FallIncidentAccepted(BaseModel):
    incidentId: str
    status: FallIncidentStatus
    confirmUrl: str


class FallActionResult(BaseModel):
    incidentId: str
    status: FallIncidentStatus
    message: str


class FallPolicy(BaseModel):
    autoReportSec: int = Field(..., description="확인 링크 미응답 시 자동 신고까지 대기 시간(초). 테스트 기본값 60초")
