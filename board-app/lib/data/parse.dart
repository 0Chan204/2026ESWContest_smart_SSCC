// 백엔드 응답 검사 · 변환 (React httpSource.ts 의 mapXxx 와 같은 규칙).
//
// 원칙: 서버 응답은 그대로 믿지 않는다. 필요한 필드만 골라 형태를 확인한 뒤 화면 형식으로 바꾸고,
// 모르는 값·빠진 값은 안전한 기본값으로 둔다. 어떤 입력이 와도 예외를 던지지 않는다.

import '../models/types.dart';

typedef Obj = Map<String, dynamic>;

// ── 작은 검사 도구 ─────────────────────────────────────────────────────────
Obj? obj(Object? v) {
  if (v is Map) {
    try {
      return v.map((k, value) => MapEntry(k.toString(), value));
    } catch (_) {
      return null;
    }
  }
  return null;
}

String str(Object? v, [String fallback = '']) => v is String ? v : fallback;
String? optStr(Object? v) => v is String ? v : null;

double numOr(Object? v, [double fallback = 0]) => (v is num && v.isFinite) ? v.toDouble() : fallback;
double? optNum(Object? v) => (v is num && v.isFinite) ? v.toDouble() : null;
List<Object?> arr(Object? v) => v is List ? List<Object?>.from(v) : const [];
List<Obj> objs(Object? v) => arr(v).map(obj).whereType<Obj>().toList();

double clampD(double v, double lo, double hi) => v < lo ? lo : (v > hi ? hi : v);
double clamp01(double v) => clampD(v, 0, 1);

DateTime? parseIso(String? s) {
  if (s == null || s.isEmpty) return null;
  return DateTime.tryParse(s);
}

String nowIso([DateTime? now]) => (now ?? DateTime.now()).toUtc().toIso8601String();

// ── 백엔드 값 → 화면 값 ────────────────────────────────────────────────────
/// 백엔드 구역 이름(kitchen / toilet / room …) → 화면 공간. 모르는 구역은 home
RoomId mapRoom(Object? v) {
  switch (v) {
    case 'kitchen':
      return RoomId.kitchen;
    case 'toilet':
    case 'bathroom':
      return RoomId.bathroom;
    case 'room':
    case 'bedroom':
      return RoomId.bedroom;
    default:
      return RoomId.home;
  }
}

/// 사용자 위치. 세 공간 밖의 이름(living 등)은 unknown(확인 중)
Location mapLocation(Object? v) {
  if (v == 'outside') return Location.outside;
  switch (mapRoom(v)) {
    case RoomId.kitchen:
      return Location.kitchen;
    case RoomId.bedroom:
      return Location.bedroom;
    case RoomId.bathroom:
      return Location.bathroom;
    case RoomId.home:
      return Location.unknown;
  }
}

HouseRoom? houseRoom(Object? v) {
  switch (mapLocation(v)) {
    case Location.kitchen:
      return HouseRoom.kitchen;
    case Location.bedroom:
      return HouseRoom.bedroom;
    case Location.bathroom:
      return HouseRoom.bathroom;
    case Location.outside:
    case Location.unknown:
      return null;
  }
}

/// 최종 재실 판단 1건 (sensing.result · GET /sensing/results)
SensingSample? mapSensing(Object? raw) {
  final v = obj(raw);
  if (v == null) return null;
  final at = v['observedAt'];
  if (at is! String || parseIso(at) == null) return null;
  final room = houseRoom(v['room']);
  final conf = optNum(v['confidence']);
  final actConf = optNum(v['activityConfidence']);
  final activity = optStr(v['activity']);
  final present = v['present'];
  return SensingSample(
    at: at,
    room: room,
    present: present is bool ? (present && room != null) : room != null,
    confidence: conf == null ? null : clamp01(conf),
    activity: (activity == null || activity.isEmpty) ? null : (activity.length > 40 ? activity.substring(0, 40) : activity),
    activityConfidence: actConf == null ? null : clamp01(actConf),
    validSec: clampD(numOr(v['validSec'], 5), 1, 600),
  );
}

AirQuality? mapAirQuality(Object? raw) {
  final v = obj(raw);
  if (v == null) return null;
  final level = switch (v['level']) { 'good' => AirLevel.good, 'normal' => AirLevel.normal, 'bad' => AirLevel.bad, _ => null };
  final q = AirQuality(pm25: optNum(v['pm25']), pm10: optNum(v['pm10']), level: level);
  return (q.pm25 == null && q.pm10 == null && q.level == null) ? null : q;
}

BurnerState? burnerState(Object? v) => switch (v) {
      'off' => BurnerState.off,
      'on' => BurnerState.on,
      'overheated' => BurnerState.overheated,
      'cooling' => BurnerState.cooling,
      _ => null,
    };

Burner? mapBurner(Object? raw) {
  final v = obj(raw);
  if (v == null) return null;
  return Burner(
    burnerId: str(v['burnerId'], 'burner-1'),
    deviceState: burnerState(v['deviceState']) ?? BurnerState.off,
    level: clampD(numOr(v['level']), 0, 9).round(),
    temperature: numOr(v['temperature'], 25),
    activeSec: numOr(v['activeSec']) < 0 ? 0 : numOr(v['activeSec']),
  );
}

Publisher? mapPublisher(Object? raw) {
  final v = obj(raw);
  if (v == null) return null;
  return switch (v['publisher']) { 'user' => Publisher.user, 'system' => Publisher.system, 'api' => Publisher.api, _ => null };
}

Presence? mapPresence(Object? raw, [DateTime? now]) {
  final v = obj(raw);
  if (v == null) return null;
  final room = mapRoom(v['room']);
  if (room != RoomId.kitchen && room != RoomId.bathroom) return null;
  return Presence(
    room: room,
    present: v['present'] == true,
    zone: switch (v['zone']) { 'kitchen' => Zone.kitchen, 'near' => Zone.near, 'far' => Zone.far, _ => Zone.unknown },
    absentSec: numOr(v['absentSec']) < 0 ? 0 : numOr(v['absentSec']),
    confidence: clamp01(numOr(v['confidence'])),
    observedAt: str(v['observedAt'], nowIso(now)),
  );
}

/// 아직 재실 판단 결과가 없을 때 쓰는 자리 (신뢰도 0)
Presence unknownPresence(RoomId room, [DateTime? now]) =>
    Presence(room: room, present: false, zone: Zone.unknown, absentSec: 0, confidence: 0, observedAt: nowIso(now));

SafetyEvent? mapEvent(Object? raw, [DateTime? now]) {
  final v = obj(raw);
  if (v == null) return null;
  final id = v['eventId'];
  final at = v['occurredAt'];
  if (id is! String || at is! String) return null;
  final type = SafetyEventType.fromWire(v['type']);
  if (type == null) return null;
  Feedback? fb;
  final f = obj(v['feedback']);
  if (f != null && (f['verdict'] == 'approved' || f['verdict'] == 'rejected')) {
    fb = Feedback(verdict: f['verdict'] == 'approved' ? Verdict.approved : Verdict.rejected, submittedAt: str(f['submittedAt'], nowIso(now)));
  }
  return SafetyEvent(
    eventId: id,
    type: type,
    severity: switch (v['severity']) { 'warning' => Severity.warning, 'danger' => Severity.danger, _ => Severity.info },
    occurredAt: at,
    room: mapRoom(v['room']),
    sessionId: optStr(v['sessionId']),
    temperature: optNum(v['temperature']),
    trigger: optStr(v['trigger']),
    action: optStr(v['action']),
    reasoning: optStr(v['reasoning']),
    guidance: optStr(v['guidance']),
    feedback: fb,
  );
}

CookingSession? mapSession(Object? raw) {
  final v = obj(raw);
  if (v == null) return null;
  final id = v['sessionId'];
  final started = v['startedAt'];
  if (id is! String || started is! String) return null;
  return CookingSession(
    sessionId: id,
    startedAt: started,
    endedAt: optStr(v['endedAt']),
    active: v['status'] == 'active',
    peakTemperature: numOr(v['peakTemperature']),
    timeline: objs(v['timeline']).map((t) => SessionEntry(at: str(t['at']), type: str(t['type']), summary: str(t['summary']))).toList(),
  );
}

FallIncident? mapFall(Object? raw) {
  final v = obj(raw);
  if (v == null) return null;
  final id = v['incidentId'];
  final detected = v['detectedAt'];
  if (id is! String || detected is! String) return null;
  final status = switch (v['status']) {
    'pending' => FallStatus.pending,
    'resolved' => FallStatus.resolved,
    'reported' => FallStatus.reported,
    'auto_reported' => FallStatus.autoReported,
    _ => null,
  };
  if (status == null) return null;
  return FallIncident(
    incidentId: id,
    room: mapRoom(v['room']),
    status: status,
    detectedAt: detected,
    confidence: clamp01(numOr(v['confidence'])),
    autoReportAt: str(v['autoReportAt'], detected),
    stage: v['stage'] == 'user' ? FallStage.user : FallStage.guardian,
    guardianAlertAt: optStr(v['guardianAlertAt']),
    eventId: optStr(v['eventId']),
    resolvedAt: optStr(v['resolvedAt']),
    reportedAt: optStr(v['reportedAt']),
    guardianNotified: v['guardianNotified'] == true,
    userNotified: v['userNotified'] == true,
    burnerShutOff: v['shutoffSent'] == true,
    lightBlinkSent: v['lightBlinkSent'] == true,
  );
}

Contact? mapContact(Object? raw) {
  final v = obj(raw);
  if (v == null) return null;
  final name = v['name'];
  final phone = v['phone'];
  return (name is String && phone is String) ? Contact(name: name, phone: phone) : null;
}

KitchenPolicy mapPolicy(Object? raw) {
  final p = obj(raw) ?? const <String, dynamic>{};
  return KitchenPolicy(
    watchAfterSec: numOr(p['watchAfterSec'], 60),
    reduceAfterSec: numOr(p['reduceAfterSec'], 180),
    offAfterSec: numOr(p['offAfterSec'], 600),
    reduceToLevel: numOr(p['reduceToLevel'], 1),
    minConfidence: numOr(p['minConfidence'], 0.7),
    nearZoneMultiplier: numOr(p['nearZoneMultiplier'], 2),
    overheatEnterC: numOr(p['overheatEnterC'], 150),
    overheatExitC: numOr(p['overheatExitC'], 60),
    heartbeatTimeoutSec: numOr(p['heartbeatTimeoutSec'], 15),
  );
}

FallPolicy mapFallPolicy(Object? raw) {
  final p = obj(raw) ?? const <String, dynamic>{};
  return FallPolicy(autoReportSec: numOr(p['autoReportSec'], 60), userAlertWaitSec: numOr(p['userAlertWaitSec'], 30));
}

/// 시간대별 예보. 지금부터(1시간 전 포함) 12시간만, 형태가 맞는 항목만 쓴다
List<HourlyWeather>? mapHourly(Object? raw, [DateTime? now]) {
  final from = (now ?? DateTime.now()).subtract(const Duration(hours: 1));
  final items = <HourlyWeather>[];
  for (final h in objs(raw)) {
    final time = str(h['time'] ?? h['at']);
    final t = parseIso(time);
    final temp = h['temperature'];
    if (time.isEmpty || t == null || t.isBefore(from) || temp is! num || !temp.isFinite) continue;
    items.add(HourlyWeather(
      time: time,
      temperature: temp.toDouble(),
      code: numOr(h['weatherCode'] ?? h['code'], -1).round(),
      rainChance: optNum(h['precipitationProbability'] ?? h['rainChance']),
    ));
  }
  return items.isEmpty ? null : items.take(12).toList();
}

/// GET /weather → 화면 날씨. 받아 둔 날씨가 없으면 null
Weather? mapWeather(Object? raw, [DateTime? now]) {
  final r = obj(raw);
  if (r == null || r['available'] != true) return null;
  final w = obj(r['weather']);
  if (w == null) return null;
  final temp = w['temperature'];
  if (temp is! num || !temp.isFinite) return null;
  final text = str(r['text']);
  return Weather(
    location: str(w['location']),
    temperature: temp.toDouble(),
    condition: str(w['condition']),
    code: numOr(w['weatherCode'], -1).round(),
    max: optNum(w['tempMax']),
    min: optNum(w['tempMin']),
    feels: optNum(w['apparentTemperature']),
    humidity: optNum(w['humidity']),
    rainChance: optNum(w['precipitationProbability']),
    fetchedAt: optStr(w['fetchedAt']) ?? optStr(r['basedOn']),
    hourly: mapHourly(w['hourly'] ?? r['hourly'], now),
    stale: r['stale'] == true,
    text: text.length > 300 ? text.substring(0, 300) : text,
  );
}

/// voice.status data → 음성 기록 (모르는 상태·형식이면 null)
VoiceRecord? mapVoice(Object? raw) {
  final d = obj(raw);
  if (d == null) return null;
  final id = d['voiceId'];
  final status = VoiceStatus.fromWire(d['status']);
  if (id is! String || id.isEmpty || status == null) return null;
  String? clip(Object? v, int n) {
    final s = optStr(v)?.trim();
    if (s == null || s.isEmpty) return null;
    return s.length > n ? s.substring(0, n) : s;
  }

  return VoiceRecord(
    voiceId: id,
    status: status,
    text: clip(d['text'], 200),
    answer: clip(d['answer'], 500),
    confirmText: clip(d['confirmText'], 200),
    confirmDeadline: optStr(d['confirmDeadline']),
    source: _token(d['source']),
    reason: _token(d['reason']),
  );
}

/// 짧은 영문 식별자만 (button · wakeword · no_speech …). 그 밖의 값은 버린다
String? _token(Object? v) {
  final s = optStr(v);
  if (s == null || !RegExp(r'^[a-z][a-z0-9_]{0,31}$').hasMatch(s)) return null;
  return s;
}

/// GET /voice/settings · WS voice.settings → 음성 설정. wakeWord 가 없으면 null
VoiceSettings? mapVoiceSettings(Object? raw) {
  final d = obj(raw);
  if (d == null || d['wakeWord'] is! bool) return null;
  return VoiceSettings(wakeWord: d['wakeWord'] as bool, standby: d['standby'] == true);
}

const roomName = {RoomId.kitchen: '주방', RoomId.bathroom: '욕실', RoomId.bedroom: '침실', RoomId.home: '집'};

// ── 전등 · 환풍기 ──────────────────────────────────────────────────────────
/// 백엔드 전등이 받을 수 있는 밝기: 0 = off · 20 = fadeout(절전) · 100 = on
const lightSteps = [0, 20, 100];
const savingBrightness = 20;

class LightState {
  const LightState({required this.on, required this.brightness, required this.saving, required this.blinking});
  final bool on;
  final int brightness;
  final bool saving;
  final bool blinking;
}

/// 전등 상태(current_state 또는 WS device.state) → 켜짐 · 밝기 · 절전
LightState mapLightState(Obj st, [Object? savingFlag]) {
  final on = st['power'] == 'on';
  final blinking = st['mode'] == 'blink';
  if (!on) return LightState(on: false, brightness: 0, saving: false, blinking: blinking);
  final reported = clampD(numOr(st['brightness'], 100), 0, 100).round();
  final fading = st['mode'] == 'fadeout';
  final brightness = fading ? (reported < savingBrightness ? reported : savingBrightness) : reported;
  final saving = savingFlag == true || fading || (brightness > 0 && brightness <= savingBrightness);
  return LightState(on: true, brightness: brightness > 0 ? brightness : savingBrightness, saving: saving, blinking: blinking);
}

/// low · mid · high ↔ 1 · 2 · 3
int mapSpeed(Object? v, int fallback) => switch (v) { 'low' => 1, 'mid' => 2, 'high' => 3, _ => fallback };
String speedToBackend(int s) => switch (s) { 1 => 'low', 3 => 'high', _ => 'mid' };
