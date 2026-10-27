// 기기 · 공간 상태를 사람이 읽는 문장으로 (React src/lib/device.ts · rooms.ts · sensing.ts · phone.ts).
// 모든 화면(카드 · 타일 · 상세)이 같은 문구를 쓴다.

import '../models/types.dart';
import 'format.dart';
import 'labels.dart';

export 'phone.dart' show formatPhone, maskPhone;

const fanSpeedLabel = {1: '약', 2: '중', 3: '강'};

class DeviceSummary {
  const DeviceSummary({required this.active, required this.status, required this.detail, required this.risk});

  /// 켜져서 동작 중인지 (아이콘 포인트 색)
  final bool active;
  final String status;
  final String detail;
  final Risk risk;
}

DeviceSummary summarize(Device d, [DateTime? now]) {
  if (!d.online) return const DeviceSummary(active: false, status: '연결 끊김', detail: '기기 전원과 Wi-Fi 를 확인해 주세요', risk: Risk.uncertain);
  switch (d) {
    case InductionDevice(:final burner):
      final t = '${burner.temperature.round()}°C';
      switch (burner.deviceState) {
        case BurnerState.overheated:
          return DeviceSummary(active: true, status: '과열 잠금', detail: '$t · 식을 때까지 켤 수 없어요', risk: Risk.danger);
        case BurnerState.cooling:
          return DeviceSummary(active: false, status: '식는 중', detail: '$t · 아직 뜨거워요', risk: Risk.normal);
        case BurnerState.on:
          return DeviceSummary(active: true, status: '화력 ${burner.level}단', detail: '$t · ${formatDuration(burner.activeSec)}째 조리 중', risk: Risk.normal);
        case BurnerState.off:
          return DeviceSummary(active: false, status: '꺼짐', detail: '표면 $t', risk: Risk.normal);
      }
    case PurifierDevice(:final dispensing, :final lastDispense):
      if (dispensing) return const DeviceSummary(active: true, status: '출수 중', detail: '물을 따르고 있어요', risk: Risk.normal);
      return DeviceSummary(
        active: false,
        status: '대기 중',
        detail: lastDispense != null
            ? '${formatWhen(lastDispense.at, now)} ${lastDispense.auto ? '자동 ' : ''}출수 ${_ml(lastDispense.ml)}mL'
            : '출수 기록 없음',
        risk: Risk.normal,
      );
    case FanDevice(:final on, :final speed, :final auto, :final room):
      final kitchen = room == RoomId.kitchen;
      return on
          ? DeviceSummary(
              active: true,
              status: '풍량 ${fanSpeedLabel[speed] ?? '중'}',
              detail: auto ? (kitchen ? '조리에 맞춰 자동 운전 중' : '자동 운전 중') : '직접 설정한 풍량',
              risk: Risk.normal)
          : DeviceSummary(
              active: false,
              status: '꺼짐',
              detail: auto ? (kitchen ? '조리를 시작하면 자동으로 켜져요' : '필요하면 자동으로 켜져요') : '자동 운전 꺼짐',
              risk: Risk.normal);
    case LightDevice(:final blinking, :final on, :final auto, :final saving, :final brightness):
      if (blinking) return const DeviceSummary(active: true, status: '깜빡이는 중', detail: '낙상 알림', risk: Risk.normal);
      if (!on) return DeviceSummary(active: false, status: '꺼짐', detail: auto ? '사람이 들어오면 자동으로 켜져요' : '자동 점등 꺼짐', risk: Risk.normal);
      if (saving) return DeviceSummary(active: true, status: '절전 $brightness%', detail: auto ? '사람이 없어 밝기를 낮췄어요' : '절전 밝기', risk: Risk.normal);
      return DeviceSummary(active: true, status: '밝기 $brightness%', detail: auto ? '사람이 있어 자동으로 켜짐' : '직접 켬', risk: Risk.normal);
    case AirPurifierDevice():
      final level = d.airQuality?.level;
      final status = level != null ? '공기 ${airLevelLabel[level]}' : (d.on ? '켜짐' : '꺼짐');
      final reason = d.on ? airAutoReason(d) : null;
      return DeviceSummary(
        active: d.on,
        status: status,
        detail: reason ?? '${pm25Text(d)} · ${d.on ? (d.mode == AirMode.auto ? '자동 운전' : '수동 운전') : '꺼짐'}',
        risk: Risk.normal,
      );
  }
}

String _ml(double v) => v == v.roundToDouble() ? v.round().toString() : v.toStringAsFixed(1);

/// 초미세먼지 글자 (값이 없으면 '측정값 없음')
String pm25Text(AirPurifierDevice d) {
  final v = d.airQuality?.pm25;
  return v == null ? '측정값 없음' : '초미세먼지 ${v.round()}';
}

/// 자동으로 켜진 이유 문장. 자동으로 켜진 게 아니면 null. short = 좁은 칸용
String? airAutoReason(AirPurifierDevice d, {bool short = false}) {
  if (!d.auto || !d.on) return null;
  if (d.autoReason == AirAutoReason.air) return short ? '공기질 나빠 자동 켜짐' : '공기질이 나빠 자동으로 켰어요';
  if (d.autoReason == AirAutoReason.induction) return short ? '인덕션 켜져 자동 켜짐' : '인덕션이 켜져 자동으로 켰어요';
  return short ? 'HomeVIS 자동 켜짐' : 'HomeVIS 가 자동으로 켰어요';
}

/// 화면에서 쓰는 전등 밝기 (꺼져 있으면 0)
int lightLevel(LightDevice d) => d.on ? d.brightness : 0;

const brightnessStep = 10;
const savingBrightnessLevel = 20;

/// 밝기를 고를 수 있는 값으로. steps 가 있으면 가장 가까운 단계, 없으면 10% 단위
int snapBrightness(num v, [List<int>? steps]) {
  final x = v < 0 ? 0 : (v > 100 ? 100 : v);
  if (steps != null && steps.isNotEmpty) {
    var best = steps.first;
    for (final s in steps) {
      if ((s - x).abs() < (best - x).abs()) best = s;
    }
    return best;
  }
  return ((x / brightnessStep).round() * brightnessStep).toInt();
}

/// 슬라이더에서 '절전'으로 읽을 밝기
int? savingLevel(LightDevice d) {
  if (d.on && d.saving) return d.brightness;
  return (d.brightnessSteps?.contains(savingBrightnessLevel) ?? false) ? savingBrightnessLevel : null;
}

/// 밝기 글자: 0 → 꺼짐, 절전 밝기 → 절전 20%
String brightnessLabel(int v, [int? saving]) {
  if (v <= 0) return '꺼짐';
  return v == saving ? '절전 $v%' : '$v%';
}

bool isControllable(Device d) => d is FanDevice || d is LightDevice || d is AirPurifierDevice;

/// 켜고 끌 수 있는 기기의 켜짐 상태 (아니면 false)
bool deviceOn(Device d) => switch (d) {
      FanDevice(:final on) => on,
      LightDevice(:final on) => on,
      AirPurifierDevice(:final on) => on,
      _ => false,
    };

// ── 공간 문장 (React lib/rooms.ts) ─────────────────────────────────────────
class RoomLine {
  const RoomLine(this.risk, this.short, this.text);
  final Risk risk;
  final String short;
  final String text;
}

RoomLine describeKitchen(KitchenPhase phase, InductionDevice? induction, Presence? p) {
  final risk = phaseRisk(phase);
  final cooking = induction?.burner.deviceState == BurnerState.on;
  final people = p == null
      ? '확인 중'
      : p.present
          ? '사람 있음'
          : '비어 있음 ${p.absentSec > 0 ? formatDuration(p.absentSec) : ''}'.trim();
  switch (phase) {
    case KitchenPhase.overheat:
      return RoomLine(risk, '과열 잠금', '인덕션이 과열돼 잠겼어요');
    case KitchenPhase.autoOff:
      return RoomLine(risk, '전원 차단', '오래 비워서 인덕션을 껐어요');
    case KitchenPhase.autoReduced:
      return RoomLine(risk, '화력 낮춤', '사람이 없어 화력을 낮췄어요 · $people');
    case KitchenPhase.absenceWatch:
      return RoomLine(risk, '지켜보는 중', '조리 중인데 사람이 없어요 · $people');
    case KitchenPhase.normal:
      return RoomLine(
        risk,
        cooking ? '조리 중' : '안전해요',
        cooking ? '조리 중 · 화력 ${induction!.burner.level}단 · $people' : '인덕션 꺼짐 · $people',
      );
  }
}

RoomLine describeBathroom(FallIncident? fall, Presence? p) {
  if (fall?.status == FallStatus.pending) return const RoomLine(Risk.danger, '낙상 감지', '낙상 감지 · 보호자 응답 대기 중');
  return (p?.present ?? false) ? const RoomLine(Risk.normal, '사용 중', '사용 중 · 움직임 정상') : const RoomLine(Risk.normal, '비어 있어요', '비어 있음');
}

const heroTitle = {
  Risk.normal: '집 안이 안전해요',
  Risk.uncertain: '일부 기기 상태를 확인할 수 없어요',
  Risk.caution: '주방을 지켜보고 있어요',
  Risk.warning: '안전을 위해 조치했어요',
  Risk.danger: '지금 확인이 필요해요',
};

// ── 재실 판단 해석 (React lib/sensing.ts) ──────────────────────────────────
const sensingWindow = Duration(seconds: 60);

const _activity = {
  'standing': '서 있음',
  'stand': '서 있음',
  'sitting': '앉아 있음',
  'sit': '앉아 있음',
  'lying': '누워 있음',
  'lie': '누워 있음',
  'lying_down': '누워 있음',
  'walking': '걷는 중',
  'walk': '걷는 중',
  'moving': '움직이는 중',
};
const _none = {'', 'none', 'unknown', 'empty', 'null', 'idle'};
final _safeActivity = RegExp(r'^[\p{L}\p{N} _-]{1,20}$', unicode: true);

/// 행동 원문 → 화면 글자. 모르는 값은 짧고 안전한 글자만 그대로, 없으면 null
String? activityLabel(String? raw) {
  if (raw == null) return null;
  final key = raw.trim().toLowerCase();
  if (_none.contains(key)) return null;
  final known = _activity[key];
  if (known != null) return known;
  return _safeActivity.hasMatch(raw.trim()) ? raw.trim() : '동작 확인 중';
}

/// 결과가 아직 유효한지 (observedAt + validSec, 2초 여유)
bool isFresh(SensingSample? s, DateTime now) {
  if (s == null) return false;
  final t = DateTime.tryParse(s.at);
  if (t == null) return false;
  final valid = s.validSec < 1 ? 1 : s.validSec;
  return now.millisecondsSinceEpoch - t.millisecondsSinceEpoch <= (valid + 2) * 1000;
}

enum Freshness { live, stale, none }

class RoomPresenceView {
  const RoomPresenceView(this.freshness, this.present, this.percent, this.activity);
  final Freshness freshness;
  final bool present;

  /// 0~100. 사람이 있는 공간이고 신뢰도를 보냈을 때만
  final int? percent;
  final String? activity;
}

RoomPresenceView roomPresence(SensingSample? latest, HouseRoom room, DateTime now) {
  if (latest == null) return const RoomPresenceView(Freshness.none, false, null, null);
  final here = latest.present && latest.room == room;
  return RoomPresenceView(
    isFresh(latest, now) ? Freshness.live : Freshness.stale,
    here,
    here && latest.confidence != null ? (latest.confidence! * 100).round() : null,
    here ? activityLabel(latest.activity) : null,
  );
}

/// 최근 1분 동안 그 공간의 재실 신뢰도 (없던 순간 0, 신뢰도가 없으면 있음=100)
List<double> roomSeries(List<SensingSample> history, HouseRoom room, DateTime now) {
  final from = now.subtract(sensingWindow);
  return [
    for (final s in history)
      if (!(DateTime.tryParse(s.at)?.isBefore(from) ?? true)) (s.present && s.room == room) ? ((s.confidence ?? 1) * 100).roundToDouble() : 0,
  ];
}

const nodeStatusLabel = {NodeStatus.ok: '정상', NodeStatus.stale: '응답 없음', NodeStatus.missing: '연결 안 됨', NodeStatus.other: '점검 필요'};

/// 신호 세기 4단계 (dBm)
int rssiBars(double? rssi) {
  if (rssi == null) return 0;
  if (rssi >= -55) return 4;
  if (rssi >= -67) return 3;
  if (rssi >= -75) return 2;
  return 1;
}
