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

v0.3.1 추가 (낙상 대응 단계화):
- FallIncident에 stage / guardianAlertAt / userNotified / lightBlinkSent 등 단계 정보 추가
- FallPolicy에 userAlertWaitSec(사용자 -> 보호자 대기 시간) 추가
- SafetyEventType에 fall_escalated, SmsPurpose에 fall_user_alert 추가

v0.4 추가 (엣지 노드 · 최종 재실 판단 결과):
- SensingResultIn / SensingResult: 재실 판단 담당이 보낸 최종 결과 (형식 확정 전이라 추가 필드도 그대로 보관)

v0.4.1 추가:
- AiDecisionRequest / AiDecisionRecord에 announcement(음성 안내 문장), expiresAt(만료 시각), status(executed/expired)
"""

import re
from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

DeviceState = Literal["off", "on", "overheated", "cooling"]

# v0.3: 가전 종류 (app/device_registry.py 참고). v0.5: 환풍기(fan), v0.7: 공기청정기(air_purifier) 추가
DeviceType = Literal["stove", "light", "water_purifier", "fan", "air_purifier"]

# v0.5: 환풍기 풍량 (약 / 중 / 강)
FanSpeed = Literal["low", "mid", "high"]

# v0.7: 공기청정기 운전 모드 (auto: 공기질에 따라 기기가 스스로 켜고 끔 / manual: 수동)
AirPurifierMode = Literal["auto", "manual"]


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
    # turn_on/turn_off/set_level: 인덕션, on/off/blink/fadeout: 전등, dispense: 정수기, on/off/set_speed: 환풍기,
    # on/off/set_mode: 공기청정기
    type: Literal["turn_on", "turn_off", "set_level", "on", "off", "blink", "fadeout", "dispense", "set_speed", "set_mode"]
    level: Optional[int] = None
    # user: 사용자(대시보드), system: 서버 자체 조치(낙상 비상 차단 등), ai: AI 중앙 판정 엔진의 판단
    actor: Literal["user", "system", "ai"]
    reason: Optional[str] = None
    issuedAt: str
    ackedAt: Optional[str] = None
    # v0.3 추가 (예전 기록에는 없을 수 있음)
    deviceId: Optional[str] = None
    deviceType: Optional[DeviceType] = None
    durationSec: Optional[int] = None
    amountMl: Optional[int] = None
    decisionId: Optional[str] = None
    # v0.5 추가
    brightness: Optional[int] = None
    speed: Optional[FanSpeed] = None
    # v0.7 추가
    mode: Optional[AirPurifierMode] = None


# ---------------------------------------------------------------------------
# 2-1. 전등·정수기 (v0.3) - 가전 <-> 서버 MQTT 메시지, 조회/제어 REST
# ---------------------------------------------------------------------------

class LightState(BaseModel):
    """전등 -> 서버 state 토픽 메시지"""

    reportedAt: str
    power: Literal["on", "off"]
    # v0.5: 밝기(%). 예전 전등처럼 보내지 않으면 power가 on일 때 100으로 봅니다.
    brightness: Optional[int] = Field(default=None, ge=0, le=100, description="밝기(%) 0~100")
    # steady: 일정한 밝기, blink: 깜빡임, fadeout(v0.5): 절전 밝기로 서서히 낮추는 중(또는 낮춘 상태)
    mode: Literal["steady", "blink", "fadeout"] = "steady"
    lastControl: Optional[LastControl] = None


class FanState(BaseModel):
    """환풍기 -> 서버 state 토픽 메시지 (v0.5)"""

    reportedAt: str
    power: Literal["on", "off"]
    speed: Optional[FanSpeed] = Field(default=None, description="풍량 low(약) / mid(중) / high(강)")
    lastControl: Optional[LastControl] = None


AirLevel = Literal["good", "normal", "bad", "very_bad"]


class AirQuality(BaseModel):
    """공기청정기 센서 값 (v0.7, v0.11: ppm 하나 + 등급 4단계). 등급 판단 기준은 임베디드가 정합니다."""

    model_config = ConfigDict(extra="allow")

    ppm: Optional[float] = Field(default=None, ge=0, description="(v0.11) 공기질 (ppm). 대시보드는 이 값만 표시")
    level: Optional[AirLevel] = Field(
        default=None, description="공기질 등급: good(좋음) / normal(보통) / bad(나쁨) / very_bad(매우 나쁨, v0.11)"
    )
    # v0.7 형식. 지금은 ppm을 쓰지만, 보내면 그대로 저장합니다 (대시보드는 표시하지 않음)
    pm25: Optional[float] = Field(default=None, ge=0, description="(예전 형식) 초미세먼지 PM2.5 (㎍/㎥)")
    pm10: Optional[float] = Field(default=None, ge=0, description="(예전 형식) 미세먼지 PM10 (㎍/㎥)")


class AirPurifierState(BaseModel):
    """공기청정기 -> 서버 state 토픽 메시지 (v0.7)
    공기질이 나쁘면 기기가 스스로 켜고 lastControl.publisher를 system으로 보냅니다."""

    reportedAt: str
    power: Literal["on", "off"]
    mode: Optional[AirPurifierMode] = Field(default=None, description="auto(공기질 자동) / manual(수동)")
    airQuality: Optional[AirQuality] = None
    lastControl: Optional[LastControl] = None


class WaterPurifierState(BaseModel):
    """정수기 -> 서버 state 토픽 메시지"""

    reportedAt: str
    status: Literal["idle", "dispensing"]
    lastDispensedMl: Optional[int] = None
    lastControl: Optional[LastControl] = None


HomeDeviceCommandType = Literal["on", "off", "blink", "fadeout", "dispense", "set_speed", "set_mode"]


class HomeDeviceCommandRequest(BaseModel):
    """전등·정수기·환풍기·공기청정기 제어 요청 (대시보드 REST, AI 판단 실행에 공통 사용)"""

    type: HomeDeviceCommandType
    durationSec: Optional[int] = Field(
        default=None, ge=1, le=600, description="blink 시간(초, 기본 10초) / fadeout에 걸리는 시간(초, 기본 LIGHT_FADE_SEC)"
    )
    amountMl: Optional[int] = Field(default=None, ge=1, le=2000, description="dispense 출수량(ml). 필수")
    speed: Optional[FanSpeed] = Field(default=None, description="set_speed 풍량 low / mid / high. 필수")
    mode: Optional[AirPurifierMode] = Field(default=None, description="공기청정기 set_mode 운전 모드 auto / manual. 필수")


class HomeDeviceCommandOut(BaseModel):
    """서버 -> 전등·정수기·환풍기·공기청정기 command 토픽 메시지"""

    commandId: str
    issuedAt: str
    deviceId: str
    type: HomeDeviceCommandType
    durationSec: Optional[int] = None
    amountMl: Optional[int] = None
    brightness: Optional[int] = Field(default=None, description="on: 100, fadeout: 절전 밝기(기본 20)")
    speed: Optional[FanSpeed] = None
    mode: Optional[AirPurifierMode] = None


class HomeDeviceAck(BaseModel):
    """전등·정수기·환풍기·공기청정기 -> 서버 ack 토픽 메시지. state는 처리 후 기기 상태(각 기기의 state 형식)"""

    commandId: str
    result: Literal["applied", "rejected", "failed"]
    appliedAt: str
    state: Optional[dict] = None


class DeviceInfo(BaseModel):
    """가전 1대의 현재 상태 (AI 판정 엔진과 대시보드에 공통으로 제공)"""

    device: DeviceType
    deviceId: str
    room: str
    online: bool
    is_on: bool
    current_state: Optional[dict] = None
    control_state: Optional[Literal["user", "homevis"]] = Field(
        default=None, description="마지막으로 상태를 바꾼 주체. user: 사용자, homevis: HomeVIS 자동 제어"
    )
    updatedAt: Optional[str] = None


class DeviceListResponse(BaseModel):
    items: list[DeviceInfo]


class DeviceCommandAccepted(BaseModel):
    commandId: str
    deviceId: str
    status: Literal["pending"] = "pending"
    issuedAt: str


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
    # v0.3.1: 사용자가 응답하지 않아 보호자에게 알림을 넘김
    "fall_escalated",
    # v0.3: AI 중앙 판정 엔진의 판단으로 가전을 제어함
    "ai_control",
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
    decisionId: Optional[str] = None  # v0.3: AI 판단으로 생긴 이벤트면 그 판단의 id


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
    devices: list[DeviceInfo] = Field(default_factory=list)  # v0.3: 인덕션·전등·정수기 전체


class StreamEnvelope(BaseModel):
    """WebSocket /stream 으로 나가는 모든 메시지가 공통으로 따르는 봉투 형식."""

    event: str
    at: str
    data: dict


# ---------------------------------------------------------------------------
# 8. 낙상 사고 안전 기능 (v0.2.1 추가)
#
# 흐름 (v0.3.1 단계화): 낙상 감지 -> POST /safety/fall-events 또는 AI 판단(fall_detected) -> 서버가
#   즉시: 인덕션 비상 전원 차단(0단계) + 전등 깜빡임 + 안전 이벤트 생성/대시보드 알림
#   1차: 사용자 본인에게 확인 링크 문자 (+ 위의 대시보드 알림)
#   2차: policy.userAlertWaitSec 안에 응답이 없으면 보호자에게 확인 링크 문자
#        (사용자 문자를 못 보내도 대시보드로 응답할 수 있으므로 대기는 그대로. 0이면 동시에 알림)
#   3차: 보호자 알림 뒤 policy.autoReportSec 안에도 응답이 없으면 자동 "신고" 처리
# 사용자/보호자가 링크(프론트의 모바일 페이지)에서 "해결"(괜찮음) 또는 "신고"를 누르면
# 그 페이지가 POST .../resolve 또는 .../report를 호출하고, 그 뒤 단계는 진행되지 않습니다.
# ---------------------------------------------------------------------------

def _check_iso_time(value: str) -> str:
    """ISO 8601 시각인지 확인합니다 ('Z'로 끝나는 UTC 표기도 허용)"""
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("ISO 8601 시각이어야 합니다. 예: 2026-10-17T12:00:02+00:00") from exc
    return value


def _normalize_phone(value: str) -> str:
    """'010-1234-5678', '010 1234 5678' 처럼 들어와도 숫자만 남겨 저장합니다.
    (문자 발송 API가 숫자만 있는 번호를 요구하기 때문)"""
    digits = re.sub(r"\D", "", value)
    if not (9 <= len(digits) <= 11) or not digits.startswith("0"):
        raise ValueError("전화번호 형식이 올바르지 않습니다. 예: 01012345678 또는 010-1234-5678")
    return digits


class UserContact(BaseModel):
    """대시보드에서 등록/수정하는 사용자(거주자 본인) 연락처.
    낙상이 감지되면 이 번호로 먼저(1차) 확인 링크 문자가 갑니다. (v0.3.1)"""

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


# fall_alert: 보호자에게 보내는 낙상 알림 / fall_user_alert: 사용자 본인에게 보내는 1차 낙상 알림
SmsPurpose = Literal["user_verification", "guardian_verification", "fall_alert", "fall_user_alert"]


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
# 지금 응답을 기다리는 단계: user(사용자 본인 응답 대기) -> guardian(보호자 응답 대기)
FallStage = Literal["user", "guardian"]


class FallIncident(BaseModel):
    """낙상 사건 하나의 전체 생애주기를 추적하는 레코드."""

    incidentId: str
    room: str
    status: FallIncidentStatus
    detectedAt: str
    confidence: float
    confirmUrl: str = Field(..., description="SMS로 발송되는, 프론트의 모바일 확인 페이지 링크")
    autoReportAt: str = Field(..., description="이 시각까지 응답이 없으면 자동으로 신고 처리됨")
    stage: FallStage = Field(
        default="guardian",
        description="지금 응답을 기다리는 대상. user면 guardianAlertAt에 보호자에게 넘어감",
    )
    guardianAlertAt: Optional[str] = Field(
        default=None, description="사용자가 응답하지 않으면 이 시각에 보호자에게 알림 (stage=user일 때)"
    )
    guardianAlertedAt: Optional[str] = Field(default=None, description="보호자 알림 단계로 넘어간 시각")
    userNotified: bool = Field(default=False, description="사용자 본인에게 1차 문자를 발송했는지 여부")
    lightBlinkSent: bool = Field(default=False, description="전등 깜빡임 명령을 전송했는지 여부")
    lightDeviceId: Optional[str] = Field(default=None, description="깜빡임 명령을 보낸 전등")
    shutoffSent: bool = Field(
        default=False,
        description="인덕션 차단 명령을 전송했는지 여부. 전송 성공이며, 실제로 꺼졌는지는 인덕션 상태로 확인",
    )
    guardianNotified: bool = Field(
        default=False,
        description="보호자에게 문자를 발송했는지 여부. 보호자 미등록이거나 발송 실패면 false",
    )
    eventId: Optional[str] = None
    resolvedAt: Optional[str] = None
    reportedAt: Optional[str] = None


class FallIncidentAccepted(BaseModel):
    incidentId: str
    status: FallIncidentStatus
    confirmUrl: str
    shutoffSent: bool
    guardianNotified: bool
    userNotified: bool = False
    lightBlinkSent: bool = False
    stage: FallStage = "guardian"
    guardianAlertAt: Optional[str] = None
    autoReportAt: Optional[str] = None


class FallActionResult(BaseModel):
    incidentId: str
    status: FallIncidentStatus
    message: str


class FallPolicy(BaseModel):
    userAlertWaitSec: int = Field(
        default=30,
        ge=0,
        description="사용자 본인이 응답하지 않을 때 보호자에게 알리기까지 대기 시간(초). 0이면 사용자와 보호자에게 동시에 알림",
    )
    autoReportSec: int = Field(
        ..., ge=0, description="보호자 알림 뒤에도 응답이 없을 때 자동 신고까지 대기 시간(초). 테스트 기본값 60초"
    )


# ---------------------------------------------------------------------------
# 9. AI 중앙 판정 엔진 -> 서버 (v0.3)
#
# 모든 판단은 AI 중앙 판정 엔진이 하고, 서버는 결과를 받아 가전을 제어하고 기록합니다.
# ---------------------------------------------------------------------------

AiActionName = Literal[
    "turn_on", "turn_off", "set_level", "restore_power", "on", "off", "blink", "fadeout", "dispense", "set_speed",
    "set_mode",
]


class AiAction(BaseModel):
    """판단 결과로 실행할 가전 제어 1건"""

    device: DeviceType
    deviceId: Optional[str] = Field(default=None, description="없으면 room(또는 첫 번째) 기준으로 서버가 고름")
    action: AiActionName
    level: Optional[int] = Field(default=None, ge=1, le=9, description="set_level 화력")
    durationSec: Optional[int] = Field(default=None, ge=1, le=600, description="blink 시간(초). 없으면 기본 10초")
    amountMl: Optional[int] = Field(default=None, ge=1, le=2000, description="dispense 출수량(ml). 필수")
    speed: Optional[FanSpeed] = Field(default=None, description="환풍기 set_speed 풍량 low / mid / high. 필수")
    mode: Optional[AirPurifierMode] = Field(default=None, description="공기청정기 set_mode 운전 모드 auto / manual. 필수")


class AiDecisionRequest(BaseModel):
    decisionId: str = Field(..., min_length=1, max_length=100, description="판단 id. 같은 id로 다시 보내면 다시 실행하지 않음")
    scenario: str = Field(
        ...,
        description="bedtime_light_off / stove_absence / fall_detected / water_dispense / power_saving / power_saving_end / "
        "away_all_off / voice_command 등",
    )
    confidence: float = Field(..., ge=0.0, le=1.0)
    reason: Optional[str] = None
    timestamp: str
    room: Optional[str] = None
    actions: list[AiAction] = Field(default_factory=list)
    weatherBriefing: bool = Field(default=False, description="true면 서버가 날씨 안내를 만들어 대시보드에 보내고 응답(weather)에 담음")
    announcement: Optional[str] = Field(
        default=None,
        min_length=1,
        max_length=500,
        description="대시보드가 화면에 띄우고 음성으로 읽을 안내 문장 (v0.4.1)",
    )
    expiresAt: Optional[str] = Field(
        default=None,
        description="이 시각이 지나서 도착한 판단은 실행하지 않고 expired로 기록 (ISO 8601). 낙상(fall_detected)은 예외",
    )

    voiceId: Optional[str] = Field(
        default=None, description="(v0.6) 음성 명령(home/voice/request)에 대한 판단이면 그 voiceId"
    )
    requiresConfirmation: bool = Field(
        default=False,
        description="(v0.6) true면 actions를 바로 실행하지 않고 사용자 확인(대시보드 확인 창)을 받은 뒤 실행. 음성 명령에서만 사용",
    )

    _expires = field_validator("expiresAt")(lambda value: value if value is None else _check_iso_time(value))


class AiActionResult(BaseModel):
    device: DeviceType
    deviceId: Optional[str] = None
    action: AiActionName
    # pending(v0.6): 사용자 확인 대기 / cancelled(v0.6): 사용자가 취소했거나 확인 시간이 지남
    status: Literal["sent", "rejected", "failed", "pending", "cancelled"]
    commandId: Optional[str] = None
    message: Optional[str] = None


class AiDecisionRecord(BaseModel):
    decisionId: str
    scenario: str
    confidence: float
    reason: Optional[str] = None
    timestamp: str
    room: Optional[str] = None
    receivedAt: str
    weatherBriefing: bool = False
    actions: list[AiActionResult] = Field(default_factory=list)
    eventId: Optional[str] = None
    fallIncidentId: Optional[str] = None
    feedback: Optional[SafetyEventFeedbackRecord] = None
    weather: Optional["WeatherBriefing"] = Field(default=None, description="weatherBriefing=true일 때 만든 날씨 안내")
    announcement: Optional[str] = None
    expiresAt: Optional[str] = None
    status: Literal["executed", "expired", "awaiting_confirmation", "cancelled"] = Field(
        default="executed",
        description="executed: 실행함 / expired: 만료 시각이 지나(또는 음성 명령이 이미 끝나) 실행하지 않음 / "
        "awaiting_confirmation: 사용자 확인 대기 / cancelled: 사용자가 취소함 (v0.6)",
    )
    voiceId: Optional[str] = None
    requiresConfirmation: bool = False


class AiDecisionAccepted(AiDecisionRecord):
    duplicate: bool = Field(default=False, description="이미 받은 decisionId라 다시 실행하지 않았으면 true")


class AiDecisionListResponse(BaseModel):
    items: list[AiDecisionRecord]
    total: int


# ---------------------------------------------------------------------------
# 10. 날씨 안내 (v0.3.2)
#
# 서버가 Open-Meteo에서 날씨를 주기적으로 받아 캐시해 두고, AI 판단(weatherBriefing=true)이나
# 대시보드 요청(GET /weather)이 오면 캐시한 값으로 안내 문장을 만듭니다.
# ---------------------------------------------------------------------------

class HourlyWeather(BaseModel):
    """시간대별 예보 1칸 (v0.4.3). time은 그 시간의 시작 시각"""

    time: str = Field(..., description="예보 시각, 시간대 포함 ISO 8601 (예: 2026-10-17T20:00:00+09:00)")
    temperature: float
    weatherCode: int
    condition: str = Field(..., description="날씨 상태 한국어")
    precipitationProbability: Optional[float] = Field(default=None, description="그 시간의 강수 확률(%)")


class WeatherSnapshot(BaseModel):
    """Open-Meteo에서 받아 저장해 둔 날씨 1건"""

    location: str
    latitude: float
    longitude: float
    observedAt: str = Field(..., description="날씨 제공처의 관측 시각 (현지 시각)")
    fetchedAt: str = Field(..., description="서버가 받아온 시각 (UTC)")
    temperature: float
    apparentTemperature: Optional[float] = None
    humidity: Optional[float] = None
    weatherCode: int
    condition: str = Field(..., description="날씨 상태 한국어 (맑음, 흐림, 비 등)")
    tempMax: Optional[float] = None
    tempMin: Optional[float] = None
    precipitationProbability: Optional[float] = Field(default=None, description="오늘 최대 강수 확률(%)")
    hourly: Optional[list[HourlyWeather]] = Field(
        default=None, description="지금 시간부터 WEATHER_HOURLY_HOURS(기본 12)시간의 시간대별 예보 (v0.4.3)"
    )


class WeatherBriefing(BaseModel):
    available: bool = Field(..., description="저장된 날씨가 있으면 true")
    text: str = Field(..., description="대시보드에 그대로 보여줄 안내 문장")
    stale: bool = Field(default=False, description="WEATHER_STALE_SEC보다 오래된 날씨로 만든 안내면 true")
    basedOn: Optional[str] = Field(default=None, description="안내에 쓴 날씨를 받아온 시각 (UTC)")
    weather: Optional[WeatherSnapshot] = None


AiDecisionRecord.model_rebuild()
AiDecisionAccepted.model_rebuild()
AiDecisionListResponse.model_rebuild()


# ---------------------------------------------------------------------------
# 11. 최종 재실 판단 결과 (v0.4, docs/EDGE-MQTT.md)
#
# 재실 판단 담당이 MQTT(home/edge/result)로 보낸 최종 결과를 그대로 저장하고,
# AI 중앙 판정 엔진이 HTTP로 꺼내 씁니다. 서버는 값을 판단하지 않습니다.
# 아래에 없는 필드가 와도 버리지 않고 그대로 저장·전달합니다 (형식이 확정되기 전이라).
# ---------------------------------------------------------------------------

class SensingResultIn(BaseModel):
    """재실 판단 담당 -> 서버 (MQTT home/edge/result)"""

    model_config = ConfigDict(extra="allow")

    resultId: Optional[str] = Field(default=None, min_length=1, max_length=100, description="없으면 서버가 만듦. 같은 id는 한 번만 저장")
    observedAt: str = Field(..., description="판단 기준 시각 (ISO 8601, 시간대 포함)")
    # v0.10: 재실 + 행동추론. 재실 판단 불가면 present=null + presenceReason, 행동 판단 불가면 activity="unknown" + activityReason
    room: Optional[str] = Field(default=None, description="최종 위치 (room / kitchen / toilet). 아무도 없거나 판단 불가면 null")
    present: Optional[bool] = Field(default=None, description="사람이 있는지. 판단할 수 없으면 null (presenceReason에 이유)")
    confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0, description="재실 정확도 0~1")
    presenceReason: Optional[str] = Field(default=None, max_length=100, description="(v0.10) 재실 판단 불가 이유 (예: warming_up, gap, no_csi, config_mismatch, low_confidence)")
    activity: Optional[str] = Field(default=None, max_length=50, description="행동 결과 (예: standing, lying). 판단할 수 없으면 \"unknown\"")
    activityConfidence: Optional[float] = Field(default=None, ge=0.0, le=1.0, description="행동 정확도 0~1")
    activityReason: Optional[str] = Field(default=None, max_length=100, description="(v0.10) 행동 판단 불가 이유 (activity가 unknown일 때)")
    modelVersion: Optional[str] = None
    validSec: Optional[int] = Field(default=None, ge=0, description="결과를 유효하게 볼 시간(초). 판단은 받는 쪽에서 함")

    _observed = field_validator("observedAt")(_check_iso_time)


class SensingResult(SensingResultIn):
    """저장된 최종 결과 (서버가 resultId, savedAt을 붙임)"""

    resultId: str
    savedAt: str = Field(..., description="서버가 저장한 시각 (UTC)")


class SensingResultListResponse(BaseModel):
    items: list[SensingResult] = Field(..., description="오래된 것부터")
    total: int = Field(..., description="조건에 맞는 전체 개수 (items는 그중 최근 limit개)")



# ---------------------------------------------------------------------------
# 12. 음성 명령 (v0.6)
#
# 대시보드가 브라우저 음성 인식으로 만든 전체 문장을 받아 저장하고, AI 판정 엔진에 MQTT로 전달합니다.
# 판정 엔진은 POST /ai/decisions(voiceId 포함)로 답변·제어를 보내고, 서버는 진행 상황을 WebSocket
# voice.status로 대시보드에 알립니다. 흐름과 형식은 docs/VOICE.md 참고.
# ---------------------------------------------------------------------------

# v0.9: listening(보드 마이크로 듣는 중), recognizing(음성 인식 중) 추가
VoiceStatus = Literal[
    "listening", "recognizing",
    "received", "thinking", "confirm_required", "executed", "answered", "cancelled", "timeout", "failed",
]

# v0.9: failed 이유 (보드 마이크 음성 명령)
VoiceFailReason = Literal["mic_unavailable", "no_speech", "stt_error", "publish_failed", "interrupted"]


class VoiceCommandIn(BaseModel):
    """대시보드 -> 서버: 인식된 전체 문장"""

    text: str = Field(..., min_length=1, max_length=500, description="인식된 전체 문장")
    lang: str = Field(default="ko-KR", max_length=20)
    confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0, description="음성 인식 신뢰도")
    source: str = Field(default="voice", max_length=30, description="입력 경로 (기본 voice)")
    recognizedAt: Optional[str] = Field(default=None, description="인식이 끝난 시각 (ISO 8601)")

    _recognized = field_validator("recognizedAt")(lambda value: value if value is None else _check_iso_time(value))

    @field_validator("text")
    @classmethod
    def _strip_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("빈 문장입니다.")
        return value


class VoiceCommand(BaseModel):
    """저장된 음성 명령 1건"""

    voiceId: str
    text: str = Field(..., description="시작어를 뗀 명령 문장 (판정 엔진에 전달하는 문장)")
    rawText: Optional[str] = Field(default=None, description="대시보드가 보낸 원문 (v0.7)")
    wakeWord: bool = Field(default=False, description="문장 앞에 시작어(홈비스)가 있었으면 true (v0.7)")
    lang: str = "ko-KR"
    confidence: Optional[float] = None
    source: str = Field(default="voice", description="입력 경로: voice(문장 전송) / button(보드 마이크 버튼, v0.9) / wakeword(호출어)")
    recognizedAt: Optional[str] = None
    receivedAt: str
    status: VoiceStatus
    reason: Optional[VoiceFailReason] = Field(default=None, description="(v0.9) status=failed일 때 이유")
    expiresAt: str = Field(..., description="이 시각까지 판정 엔진의 판단이 없으면 timeout")
    decisionId: Optional[str] = None
    answer: Optional[str] = Field(default=None, description="사용자에게 들려줄 답변 (판정 엔진의 announcement)")
    requiresConfirmation: bool = False
    confirmText: Optional[str] = Field(default=None, description="확인 창 문구 (서버가 만듦)")
    confirmDeadline: Optional[str] = Field(default=None, description="이 시각까지 확인이 없으면 자동 취소")
    confirmedAt: Optional[str] = None
    pendingActions: list[AiAction] = Field(default_factory=list, description="확인을 기다리는 제어 (내부용)")
    actions: list[AiActionResult] = Field(default_factory=list, description="제어 결과")
    updatedAt: str


class VoiceCommandAccepted(BaseModel):
    voiceId: str
    status: Literal["received"] = "received"
    receivedAt: str


class VoiceCommandListResponse(BaseModel):
    items: list[VoiceCommand] = Field(..., description="최신순")
    total: int


class VoiceConfirmRequest(BaseModel):
    approved: bool = Field(..., description="true: 실행 / false: 취소")


# v0.9: 보드 마이크 음성 명령 (docs/VOICE.md 5장)

class VoiceListenAccepted(BaseModel):
    voiceId: str
    status: Literal["listening"] = "listening"
    receivedAt: str


class VoiceListenCancelRequest(BaseModel):
    voiceId: str = Field(..., min_length=1, max_length=128)


class VoiceSettings(BaseModel):
    """보드 음성 설정. GET/PUT /voice/settings 응답, WebSocket voice.settings"""

    wakeWord: bool = Field(default=False, description="호출어(홈비스)로 부르기")
    standby: bool = Field(default=False, description="지금 호출어를 기다리는 중인지 (상시 듣기 기능이 붙기 전까지 항상 false)")
    speak: bool = Field(default=True, description="답변·위험 안내를 보드 스피커로 읽어 주기")


class VoiceSettingsUpdate(BaseModel):
    wakeWord: Optional[bool] = None
    speak: Optional[bool] = None
