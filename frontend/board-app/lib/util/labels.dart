// 화면 글자 · 분류 (React src/lib/labels.ts)

import '../models/types.dart';

/// 평면도 순서: 주방 | 침실 | 욕실
const houseRooms = [HouseRoom.kitchen, HouseRoom.bedroom, HouseRoom.bathroom];

const roomLabel = {RoomId.kitchen: '주방', RoomId.bedroom: '침실', RoomId.bathroom: '욕실', RoomId.home: '집'};
const houseRoomLabel = {HouseRoom.kitchen: '주방', HouseRoom.bedroom: '침실', HouseRoom.bathroom: '욕실'};

const locationLabel = {
  Location.kitchen: '주방',
  Location.bedroom: '침실',
  Location.bathroom: '욕실',
  Location.outside: '외출 중',
  Location.unknown: '확인 중',
};

const airLevelLabel = {AirLevel.good: '좋음', AirLevel.normal: '보통', AirLevel.bad: '나쁨', AirLevel.veryBad: '매우 나쁨'};

const burnerLabel = {BurnerState.off: '꺼짐', BurnerState.on: '켜짐', BurnerState.overheated: '과열', BurnerState.cooling: '식는 중'};

const publisherLabel = {Publisher.user: '본체에서 조작', Publisher.system: '안전 자동 조치', Publisher.api: '앱에서 조작'};

const fallStatusLabel = {
  FallStatus.pending: '보호자 확인 대기 중',
  FallStatus.resolved: '보호자가 괜찮다고 확인했어요',
  FallStatus.reported: '보호자가 신고를 요청했어요',
  FallStatus.autoReported: '응답이 없어 자동으로 신고했어요',
};

const eventTitle = {
  SafetyEventType.cookingStarted: '조리 시작',
  SafetyEventType.absenceDetected: '주방 이탈 감지',
  SafetyEventType.autoPowerReduced: '인덕션 화력 자동 저감',
  SafetyEventType.autoPowerOff: '인덕션 전원 자동 차단',
  SafetyEventType.overheatDetected: '인덕션 과열 감지',
  SafetyEventType.commandBlocked: '과열로 켜기 차단',
  SafetyEventType.overheatCleared: '과열 해제',
  SafetyEventType.userReturned: '주방 복귀',
  SafetyEventType.cookingEnded: '조리 종료',
  SafetyEventType.fallDetected: '욕실 낙상 감지',
  SafetyEventType.fallResolved: '낙상 — 보호자 확인 완료',
  SafetyEventType.fallReported: '낙상 — 보호자 신고 요청',
  SafetyEventType.fallAutoReported: '낙상 — 자동 신고',
  SafetyEventType.fallEscalated: '낙상 — 보호자에게 알림',
  SafetyEventType.aiControl: 'AI 자동 제어',
  SafetyEventType.autoDispense: '아침 자동 출수',
};

enum EventCategory { fire, fall, routine }

EventCategory eventCategory(SafetyEventType type) {
  if (type.wire.startsWith('fall_')) return EventCategory.fall;
  if (type == SafetyEventType.autoDispense || type == SafetyEventType.aiControl) return EventCategory.routine;
  return EventCategory.fire;
}

const categoryLabel = {EventCategory.fire: '화재 예방', EventCategory.fall: '낙상', EventCategory.routine: '생활 자동화'};

/// '안전 기록'에 보여줄 이벤트: 시스템이 실제로 무언가를 한 것만
const recordTypes = {
  SafetyEventType.autoPowerReduced,
  SafetyEventType.autoPowerOff,
  SafetyEventType.overheatDetected,
  SafetyEventType.fallDetected,
  SafetyEventType.fallResolved,
  SafetyEventType.fallReported,
  SafetyEventType.fallAutoReported,
  SafetyEventType.fallEscalated,
  SafetyEventType.autoDispense,
  SafetyEventType.aiControl,
};

/// 사용자가 적절성 피드백을 남길 수 있는 자동 조치
const feedbackTypes = {
  SafetyEventType.autoPowerReduced,
  SafetyEventType.autoPowerOff,
  SafetyEventType.fallDetected,
  SafetyEventType.aiControl,
};

bool isRecord(SafetyEvent e) => recordTypes.contains(e.type);

Risk phaseRisk(KitchenPhase phase) => switch (phase) {
      KitchenPhase.absenceWatch => Risk.caution,
      KitchenPhase.autoReduced => Risk.warning,
      KitchenPhase.autoOff || KitchenPhase.overheat => Risk.danger,
      KitchenPhase.normal => Risk.normal,
    };

const _riskOrder = [Risk.normal, Risk.uncertain, Risk.caution, Risk.warning, Risk.danger];

Risk maxRisk(List<Risk> risks) {
  var best = Risk.normal;
  for (final r in risks) {
    if (_riskOrder.indexOf(r) > _riskOrder.indexOf(best)) best = r;
  }
  return best;
}

const riskLabel = {Risk.normal: '안전', Risk.caution: '주의', Risk.warning: '경고', Risk.danger: '위험', Risk.uncertain: '확인 필요'};
