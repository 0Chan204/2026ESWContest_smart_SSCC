// 화면 도메인 타입. React v5 `src/types/index.ts` · `src/data/source/types.ts` 와 같은 구조.
//
// 백엔드 값(app/schemas.py)은 data/parse.dart 에서 검사한 뒤 이 형식으로 바꾼다.
// 화면은 이 타입만 안다.

enum AppMode { normal, elderly }

enum ThemeChoice { light, dark, system }

/// 부스 구성: 주방 · 침실 · 욕실 (백엔드 kitchen / room / toilet)
enum HouseRoom { kitchen, bedroom, bathroom }

/// 기기·기록의 공간. 백엔드가 모르는 구역 이름을 보내면 home(집 전체)
enum RoomId { kitchen, bedroom, bathroom, home }

/// 사용자 현재 위치 (집 밖 / 판단 불가 포함)
enum Location { kitchen, bedroom, bathroom, outside, unknown }

extension HouseRoomX on HouseRoom {
  RoomId get roomId => RoomId.values.byName(name);
  Location get location => Location.values.byName(name);
}

/// 화면에 보여줄 위험 단계
enum Risk { normal, caution, warning, danger, uncertain }

// ── 인덕션 ────────────────────────────────────────────────────────────────
enum BurnerState { off, on, overheated, cooling }

enum Publisher { user, system, api }

class Burner {
  const Burner({
    required this.burnerId,
    required this.deviceState,
    required this.level,
    required this.temperature,
    required this.activeSec,
  });

  final String burnerId;
  final BurnerState deviceState;

  /// 0~9
  final int level;
  final double temperature;
  final double activeSec;
}

/// BE compute_safety_phase() 와 같은 값
enum KitchenPhase { normal, absenceWatch, autoReduced, autoOff, overheat }

// ── 기기 ─────────────────────────────────────────────────────────────────
enum DeviceKind { induction, purifier, fan, light, air }

sealed class Device {
  const Device({required this.id, required this.name, required this.room, required this.online});

  final String id;
  final String name;
  final RoomId room;
  final bool online;

  DeviceKind get kind;

  /// 온라인 여부만 바꾼 사본
  Device withOnline(bool online);
}

class InductionDevice extends Device {
  const InductionDevice({
    required super.id,
    required super.name,
    required super.room,
    required super.online,
    required this.burner,
    required this.lastControl,
    required this.alarm,
    required this.tempHistory,
  });

  final Burner burner;

  /// 마지막으로 상태를 바꾼 주체 (user=본체 조작, system=안전 자동 조치)
  final Publisher lastControl;
  final bool alarm;

  /// 온도 추이 (마지막 원소가 최신)
  final List<double> tempHistory;

  @override
  DeviceKind get kind => DeviceKind.induction;

  InductionDevice copyWith({Burner? burner, bool? online, Publisher? lastControl, bool? alarm, List<double>? tempHistory}) =>
      InductionDevice(
        id: id,
        name: name,
        room: room,
        online: online ?? this.online,
        burner: burner ?? this.burner,
        lastControl: lastControl ?? this.lastControl,
        alarm: alarm ?? this.alarm,
        tempHistory: tempHistory ?? this.tempHistory,
      );

  @override
  InductionDevice withOnline(bool online) => copyWith(online: online);
}

class LastDispense {
  const LastDispense({required this.at, required this.ml, required this.auto});
  final String at;
  final double ml;
  final bool auto;
}

/// 정수기 (조회 전용)
class PurifierDevice extends Device {
  const PurifierDevice({
    required super.id,
    required super.name,
    required super.room,
    required super.online,
    required this.dispensing,
    required this.lastDispense,
    required this.autoDispensedToday,
  });

  final bool dispensing;
  final LastDispense? lastDispense;
  final bool autoDispensedToday;

  @override
  DeviceKind get kind => DeviceKind.purifier;

  PurifierDevice copyWith({bool? online, bool? dispensing, LastDispense? lastDispense}) => PurifierDevice(
        id: id,
        name: name,
        room: room,
        online: online ?? this.online,
        dispensing: dispensing ?? this.dispensing,
        lastDispense: lastDispense ?? this.lastDispense,
        autoDispensedToday: autoDispensedToday,
      );

  @override
  PurifierDevice withOnline(bool online) => copyWith(online: online);
}

class FanDevice extends Device {
  const FanDevice({
    required super.id,
    required super.name,
    required super.room,
    required super.online,
    required this.on,
    required this.speed,
    required this.auto,
  });

  final bool on;

  /// 풍량 1~3 (약 · 중 · 강)
  final int speed;
  final bool auto;

  @override
  DeviceKind get kind => DeviceKind.fan;

  FanDevice copyWith({bool? online, bool? on, int? speed, bool? auto}) => FanDevice(
        id: id,
        name: name,
        room: room,
        online: online ?? this.online,
        on: on ?? this.on,
        speed: speed ?? this.speed,
        auto: auto ?? this.auto,
      );

  @override
  FanDevice withOnline(bool online) => copyWith(online: online);
}

class LightDevice extends Device {
  const LightDevice({
    required super.id,
    required super.name,
    required super.room,
    required super.online,
    required this.on,
    required this.brightness,
    required this.auto,
    this.brightnessSteps,
    this.saving = false,
    this.blinking = false,
  });

  final bool on;

  /// 밝기 % (켜져 있을 때 의미가 있다)
  final int brightness;
  final bool auto;

  /// 고를 수 있는 밝기 단계(%, 0 = 끔). 백엔드 전등은 [0, 20, 100]
  final List<int>? brightnessSteps;

  /// 절전 밝기로 낮춘 상태
  final bool saving;

  /// 깜빡이는 중 (낙상 알림)
  final bool blinking;

  @override
  DeviceKind get kind => DeviceKind.light;

  LightDevice copyWith({bool? online, bool? on, int? brightness, bool? auto, bool? saving, bool? blinking}) => LightDevice(
        id: id,
        name: name,
        room: room,
        online: online ?? this.online,
        on: on ?? this.on,
        brightness: brightness ?? this.brightness,
        auto: auto ?? this.auto,
        brightnessSteps: brightnessSteps,
        saving: saving ?? this.saving,
        blinking: blinking ?? this.blinking,
      );

  @override
  LightDevice withOnline(bool online) => copyWith(online: online);
}

/// 공기질 등급 4단계 (임베디드가 판단해서 보냄)
enum AirLevel { good, normal, bad, veryBad }

enum AirMode { auto, manual }

enum AirAutoReason { air, induction }

/// 공기청정기 센서 값: 공기질 하나(ppm) + 등급
class AirQuality {
  const AirQuality({this.ppm, this.level});

  /// 공기질 (ppm)
  final double? ppm;
  final AirLevel? level;
}

/// 공기청정기 (BE air_purifier). 정수기와 다른 기기
class AirPurifierDevice extends Device {
  const AirPurifierDevice({
    required super.id,
    required super.name,
    required super.room,
    required super.online,
    required this.on,
    required this.mode,
    required this.auto,
    this.airQuality,
    this.autoReason,
  });

  final bool on;
  final AirMode mode;
  final AirQuality? airQuality;

  /// 마지막 변경이 HomeVIS·기기 자동 동작인지
  final bool auto;

  /// 자동으로 켠 이유 (확실히 알 때만)
  final AirAutoReason? autoReason;

  @override
  DeviceKind get kind => DeviceKind.air;

  AirPurifierDevice copyWith({
    bool? online,
    bool? on,
    AirMode? mode,
    AirQuality? airQuality,
    bool? auto,
    AirAutoReason? Function()? autoReason,
  }) =>
      AirPurifierDevice(
        id: id,
        name: name,
        room: room,
        online: online ?? this.online,
        on: on ?? this.on,
        mode: mode ?? this.mode,
        airQuality: airQuality ?? this.airQuality,
        auto: auto ?? this.auto,
        autoReason: autoReason != null ? autoReason() : this.autoReason,
      );

  @override
  AirPurifierDevice withOnline(bool online) => copyWith(online: online);
}

// ── 최종 재실 판단 (BE sensing.result) ───────────────────────────────────
class SensingSample {
  const SensingSample({
    required this.at,
    required this.room,
    required this.present,
    required this.confidence,
    required this.activity,
    required this.activityConfidence,
    required this.validSec,
  });

  /// 판단 기준 시각 (ISO)
  final String at;

  /// 사람이 있는 공간. 없거나 알 수 없으면 null
  final HouseRoom? room;
  final bool present;

  /// 0~1. 보내지 않으면 null
  final double? confidence;
  final String? activity;
  final double? activityConfidence;

  /// 결과를 유효하게 볼 시간(초)
  final double validSec;
}

enum NodeStatus { ok, stale, missing, other }

/// 공간별 센서 노드 상태 (GET /sensing/combined)
class SensingNode {
  const SensingNode({required this.room, required this.node, required this.status, this.rssi, this.rateHz});
  final HouseRoom room;
  final String node;
  final NodeStatus status;
  final double? rssi;
  final double? rateHz;
}

// ── 재실 (BE PresenceReport) ─────────────────────────────────────────────
enum Zone { kitchen, near, far, unknown }

class Presence {
  const Presence({
    required this.room,
    required this.present,
    required this.zone,
    required this.absentSec,
    required this.confidence,
    required this.observedAt,
  });

  /// kitchen 또는 bathroom
  final RoomId room;
  final bool present;
  final Zone zone;
  final double absentSec;

  /// 0~1
  final double confidence;
  final String observedAt;
}

// ── 안전 이벤트 ───────────────────────────────────────────────────────────
enum SafetyEventType {
  cookingStarted('cooking_started'),
  absenceDetected('absence_detected'),
  autoPowerReduced('auto_power_reduced'),
  autoPowerOff('auto_power_off'),
  overheatDetected('overheat_detected'),
  commandBlocked('command_blocked'),
  overheatCleared('overheat_cleared'),
  userReturned('user_returned'),
  cookingEnded('cooking_ended'),
  fallDetected('fall_detected'),
  fallResolved('fall_resolved'),
  fallReported('fall_reported'),
  fallAutoReported('fall_auto_reported'),
  fallEscalated('fall_escalated'),
  aiControl('ai_control'),
  autoDispense('auto_dispense');

  const SafetyEventType(this.wire);
  final String wire;

  static SafetyEventType? fromWire(Object? v) {
    for (final t in values) {
      if (t.wire == v) return t;
    }
    return null;
  }
}

enum Severity { info, warning, danger }

enum Verdict { approved, rejected }

class Feedback {
  const Feedback({required this.verdict, required this.submittedAt});
  final Verdict verdict;
  final String submittedAt;
}

class SafetyEvent {
  const SafetyEvent({
    required this.eventId,
    required this.type,
    required this.severity,
    required this.occurredAt,
    required this.room,
    this.sessionId,
    this.temperature,
    this.trigger,
    this.action,
    this.reasoning,
    this.guidance,
    this.feedback,
  });

  final String eventId;
  final SafetyEventType type;
  final Severity severity;
  final String occurredAt;
  final RoomId room;
  final String? sessionId;
  final double? temperature;
  final String? trigger;
  final String? action;
  final String? reasoning;
  final String? guidance;
  final Feedback? feedback;

  SafetyEvent withFeedback(Feedback? f) => SafetyEvent(
        eventId: eventId,
        type: type,
        severity: severity,
        occurredAt: occurredAt,
        room: room,
        sessionId: sessionId,
        temperature: temperature,
        trigger: trigger,
        action: action,
        reasoning: reasoning,
        guidance: guidance,
        feedback: f,
      );
}

// ── 조리 세션 ─────────────────────────────────────────────────────────────
class SessionEntry {
  const SessionEntry({required this.at, required this.type, required this.summary});
  final String at;
  final String type;
  final String summary;
}

class CookingSession {
  const CookingSession({
    required this.sessionId,
    required this.startedAt,
    required this.active,
    required this.peakTemperature,
    required this.timeline,
    this.endedAt,
  });

  final String sessionId;
  final String startedAt;
  final String? endedAt;

  /// active / ended
  final bool active;
  final double peakTemperature;
  final List<SessionEntry> timeline;
}

// ── 낙상 ─────────────────────────────────────────────────────────────────
enum FallStatus { pending, resolved, reported, autoReported }

/// 지금 응답을 기다리는 대상 (user 면 guardianAlertAt 에 보호자에게 넘어감)
enum FallStage { user, guardian }

class FallIncident {
  const FallIncident({
    required this.incidentId,
    required this.room,
    required this.status,
    required this.detectedAt,
    required this.confidence,
    required this.autoReportAt,
    this.stage = FallStage.guardian,
    this.guardianAlertAt,
    this.eventId,
    this.resolvedAt,
    this.reportedAt,
    this.guardianNotified = false,
    this.userNotified = false,
    this.burnerShutOff = false,
    this.lightBlinkSent = false,
  });

  final String incidentId;
  final RoomId room;
  final FallStatus status;
  final String detectedAt;
  final double confidence;
  final String autoReportAt;
  final FallStage stage;
  final String? guardianAlertAt;
  final String? eventId;
  final String? resolvedAt;
  final String? reportedAt;

  /// 보호자에게 문자를 실제로 보냈는지 (미등록·발송 실패면 false)
  final bool guardianNotified;
  final bool userNotified;

  /// 인덕션 비상 차단 명령을 보냈는지
  final bool burnerShutOff;
  final bool lightBlinkSent;
}

// ── 연락처 / 정책 ────────────────────────────────────────────────────────
class Contact {
  const Contact({required this.name, required this.phone});
  final String name;

  /// 숫자만
  final String phone;
}

class Contacts {
  const Contacts({this.user, this.guardian});
  final Contact? user;
  final Contact? guardian;

  Contact? of(ContactKind kind) => kind == ContactKind.guardian ? guardian : user;
  Contacts withContact(ContactKind kind, Contact c) =>
      kind == ContactKind.guardian ? Contacts(user: user, guardian: c) : Contacts(user: c, guardian: guardian);
}

/// 연락처 종류: 보호자 (PUT /guardian) · 본인 (PUT /user)
enum ContactKind { guardian, user }

class KitchenPolicy {
  const KitchenPolicy({
    this.watchAfterSec = 60,
    this.reduceAfterSec = 180,
    this.offAfterSec = 600,
    this.reduceToLevel = 1,
    this.minConfidence = 0.7,
    this.nearZoneMultiplier = 2,
    this.overheatEnterC = 150,
    this.overheatExitC = 60,
    this.heartbeatTimeoutSec = 15,
  });

  final double watchAfterSec;
  final double reduceAfterSec;
  final double offAfterSec;
  final double reduceToLevel;
  final double minConfidence;
  final double nearZoneMultiplier;
  final double overheatEnterC;
  final double overheatExitC;
  final double heartbeatTimeoutSec;
}

class FallPolicy {
  const FallPolicy({this.autoReportSec = 60, this.userAlertWaitSec = 30});
  final double autoReportSec;
  final double userAlertWaitSec;
}

// ── 날씨 ─────────────────────────────────────────────────────────────────
class HourlyWeather {
  const HourlyWeather({required this.time, required this.temperature, required this.code, this.rainChance});
  final String time;
  final double temperature;
  final int code;
  final double? rainChance;
}

class Weather {
  const Weather({
    required this.location,
    required this.temperature,
    required this.condition,
    required this.code,
    required this.stale,
    required this.text,
    this.max,
    this.min,
    this.feels,
    this.humidity,
    this.rainChance,
    this.fetchedAt,
    this.hourly,
  });

  final String location;
  final double temperature;
  final String condition;

  /// WMO 날씨 코드
  final int code;
  final double? max;
  final double? min;
  final double? feels;
  final double? humidity;
  final double? rainChance;
  final String? fetchedAt;
  final List<HourlyWeather>? hourly;
  final bool stale;
  final String text;
}

// ── 음성 명령 (docs/VOICE.md + 보드 마이크 제안 계약, README 참고) ───────────────
enum VoiceStatus {
  /// 보드 마이크가 듣는 중 (제안)
  listening('listening'),

  /// 들은 소리를 글자로 바꾸는 중 (제안, text 가 있으면 함께)
  recognizing('recognizing'),
  received('received'),
  thinking('thinking'),
  confirmRequired('confirm_required'),
  executed('executed'),
  answered('answered'),
  cancelled('cancelled'),
  timeout('timeout'),
  failed('failed');

  const VoiceStatus(this.wire);
  final String wire;

  static VoiceStatus? fromWire(Object? v) {
    for (final s in values) {
      if (s.wire == v) return s;
    }
    return null;
  }
}

/// voice.status 의 data 중 화면에 필요한 것만
class VoiceRecord {
  const VoiceRecord({
    required this.voiceId,
    required this.status,
    this.text,
    this.answer,
    this.confirmText,
    this.confirmDeadline,
    this.source,
    this.reason,
  });
  final String voiceId;
  final VoiceStatus status;

  /// 시작한 곳: button (마이크 버튼) · wakeword (호출어) … (제안)
  final String? source;

  /// failed 의 이유: mic_unavailable · no_speech … (제안)
  final String? reason;

  /// 인식한 문장 (서버가 시작어를 뗀 것)
  final String? text;
  final String? answer;
  final String? confirmText;
  final String? confirmDeadline;
}

/// 보드 음성 설정 (GET · PUT /voice/settings, WS voice.settings — 제안)
class VoiceSettings {
  const VoiceSettings({required this.wakeWord, required this.standby, this.speak});

  /// 호출어("홈비스")로 부르기
  final bool wakeWord;

  /// 지금 호출어를 기다리며 마이크가 켜져 있는지
  final bool standby;

  /// 보드 스피커로 확인 문구 · 답변 · 안내 읽기 (BE v0.9). null = 서버가 알려 주지 않음
  final bool? speak;
}

/// 기기 제어 요청 (React DeviceControl)
class DeviceControl {
  const DeviceControl({this.on, this.speed, this.brightness, this.mode});
  final bool? on;
  final int? speed;
  final int? brightness;
  final AirMode? mode;
}
