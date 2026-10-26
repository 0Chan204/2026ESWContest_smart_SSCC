import 'package:flutter_test/flutter_test.dart';
import 'package:homevis_gui/data/parse.dart';
import 'package:homevis_gui/data/stream_message.dart';
import 'package:homevis_gui/data/translator.dart';
import 'package:homevis_gui/features/alerts/status_banner.dart';
import 'package:homevis_gui/models/types.dart';
import 'package:homevis_gui/store/home_state.dart';

import 'fixtures.dart';

HomeState loaded({bool stoveOn = true}) {
  final t = BackendTranslator();
  final devices = t.buildDevices(snapshotJson(stoveOn: stoveOn));
  return applySnapshot(
    HomeState.initial(),
    Snapshot(
      devices: devices,
      kitchenPresence: mapPresence(snapshotJson()['rooms']['kitchen']['presence'])!,
      bathroomPresence: unknownPresence(RoomId.bathroom),
      location: Location.kitchen,
      sensing: const [],
      session: mapSession(snapshotJson(stoveOn: stoveOn)['session']),
      sessions: [if (mapSession(snapshotJson(stoveOn: stoveOn)['session']) != null) mapSession(snapshotJson(stoveOn: stoveOn)['session'])!],
      events: const [],
      contacts: const Contacts(),
      policy: const KitchenPolicy(),
      fallPolicy: const FallPolicy(),
    ),
  );
}

SafetyEvent ev(String id, String type, {String room = 'kitchen'}) => mapEvent(eventJson(id, type, room: room))!;

void main() {
  test('스냅샷 반영', () {
    final s = loaded();
    expect(s.ready, isTrue);
    expect(s.devices.length, 7);
    expect(s.induction!.burner.level, 5);
    expect(s.session!.sessionId, 'sess-1');
    expect(s.kitchenPhase, KitchenPhase.normal);
    // 욕실 환풍기가 끊겨 있지만 인덕션은 온라인 → 위험 없음
    expect(s.overallRisk, Risk.normal);
  });

  test('이탈 → 저감 → 차단 → 복귀 (주방 단계 · 위험 · 안내 시트)', () {
    var s = loaded();
    s = reduceMessage(s, SafetyEventMsg(ev('e1', 'absence_detected')));
    expect(s.kitchenPhase, KitchenPhase.absenceWatch);
    expect(s.kitchenRisk, Risk.caution);
    expect(s.notice, isNull);
    s = reduceMessage(s, SafetyEventMsg(ev('e2', 'auto_power_reduced')));
    expect(s.kitchenPhase, KitchenPhase.autoReduced);
    expect(s.overallRisk, Risk.warning);
    expect(s.notice!.eventId, 'e2');
    s = reduceMessage(s, SafetyEventMsg(ev('e3', 'auto_power_off')));
    expect(s.kitchenPhase, KitchenPhase.autoOff);
    expect(s.overallRisk, Risk.danger);
    s = reduceMessage(s, SafetyEventMsg(ev('e4', 'user_returned')));
    expect(s.kitchenPhase, KitchenPhase.normal);
    expect(s.events.map((e) => e.eventId), ['e4', 'e3', 'e2', 'e1']);
    // 같은 id 는 한 번만
    s = reduceMessage(s, SafetyEventMsg(ev('e4', 'user_returned')));
    expect(s.events.length, 4);
  });

  test('주방에 사람이 돌아오면 이탈 단계 해제', () {
    var s = reduceMessage(loaded(), SafetyEventMsg(ev('e1', 'absence_detected')));
    s = reduceMessage(s, PresenceMsg(mapPresence({'room': 'kitchen', 'present': true, 'confidence': 0.9})!));
    expect(s.kitchenPhase, KitchenPhase.normal);
  });

  test('과열은 화구 상태로', () {
    final s = reduceMessage(
      loaded(),
      const BurnerTelemetryMsg(
        deviceId: 'induction-01',
        reportedAt: 'now',
        burners: [Burner(burnerId: 'b', deviceState: BurnerState.overheated, level: 9, temperature: 162, activeSec: 10)],
      ),
    );
    expect(s.kitchenPhase, KitchenPhase.overheat);
    expect(s.induction!.tempHistory.last, 162);
    expect(bannerFor(s, DateTime.now())!.title, contains('과열'));
  });

  test('낙상: 경보 열림, 배너 우선순위 (경보가 닫혀 있을 때 낙상 > 과열)', () {
    var s = reduceMessage(loaded(), SafetyEventMsg(ev('e3', 'auto_power_off')));
    final fall = mapFall({'incidentId': 'f1', 'room': 'toilet', 'status': 'pending', 'detectedAt': '2026-10-26T10:00:00Z', 'autoReportAt': '2099-01-01T00:00:00Z'})!;
    s = reduceMessage(s, FallMsg(fall));
    expect(s.fallAlertOpen, isTrue);
    expect(s.bathroomRisk, Risk.danger);
    // 경보가 열려 있으면 배너는 다음 순위(자동 차단)
    expect(bannerFor(s, DateTime.now())!.title, '인덕션 전원 자동 차단');
    s = s.copyWith(fallAlertOpen: false);
    expect(bannerFor(s, DateTime.now())!.title, '욕실 낙상 감지');
    s = reduceMessage(s, FallMsg(mapFall({'incidentId': 'f1', 'status': 'resolved', 'detectedAt': 'x'})!));
    expect(s.bathroomRisk, Risk.normal);
    expect(s.fallAlertOpen, isFalse);
  });

  test('연결 끊김 배너 · 온라인 변경', () {
    var s = loaded();
    expect(bannerFor(s, DateTime.now())!.title, '욕실 환풍기 응답 없음');
    s = reduceMessage(s, const ConnectionMsg(deviceId: 'fan-02', online: true));
    expect(bannerFor(s, DateTime.now()), isNull);
    s = reduceMessage(s, const ConnectionMsg(deviceId: 'induction-01', online: false));
    expect(s.kitchenRisk, Risk.uncertain);
  });

  test('재실 판단: 같은 결과는 한 번, 최대 개수', () {
    var s = loaded();
    for (var i = 0; i < sensingKeep + 10; i++) {
      final sample = mapSensing({'observedAt': DateTime.utc(2026, 10, 26, 10, 0, i).toIso8601String(), 'room': 'kitchen', 'present': true})!;
      s = reduceMessage(s, SensingMsg(sample));
      s = reduceMessage(s, SensingMsg(sample));
    }
    expect(s.sensing.length, sensingKeep);
    s = reduceMessage(s, const LocationMsg(location: Location.bathroom, observedAt: 'now'));
    expect(s.location, Location.bathroom);
  });

  test('세션: 끝나면 진행 중 세션 해제', () {
    var s = loaded();
    s = reduceMessage(s, SessionMsg(mapSession({'sessionId': 'sess-1', 'startedAt': '2026-10-26T09:50:00Z', 'status': 'ended', 'endedAt': '2026-10-26T10:10:00Z'})!));
    expect(s.session, isNull);
    expect(s.sessions['sess-1']!.endedAt, isNotNull);
  });

  test('기기 상태 · 안내 문장 · 음성(상태 변화 없음)', () {
    var s = loaded();
    final fan = (s.deviceById('fan-01') as FanDevice).copyWith(speed: 1);
    s = reduceMessage(s, DeviceMsg(fan));
    expect((s.deviceById('fan-01') as FanDevice).speed, 1);
    s = reduceMessage(s, const AnnouncementMsg(id: 'a1', text: '안녕하세요', at: 'now'));
    expect(s.announcement!.text, '안녕하세요');
    final before = s;
    s = reduceMessage(s, const VoiceMsg(VoiceRecord(voiceId: 'v', status: VoiceStatus.thinking)));
    expect(identical(before, s), isTrue);
  });
}
