import 'package:flutter_test/flutter_test.dart';
import 'package:homevis_gui/data/home_source.dart';
import 'package:homevis_gui/data/stream_message.dart';
import 'package:homevis_gui/data/translator.dart';
import 'package:homevis_gui/models/types.dart';

import 'fixtures.dart';

T dev<T extends Device>(List<Device> ds, String id) => ds.firstWhere((d) => d.id == id) as T;

void main() {
  late BackendTranslator t;
  setUp(() {
    t = BackendTranslator();
    t.buildDevices(snapshotJson(stoveOn: true));
  });

  group('기기 목록 (GET /snapshot devices)', () {
    test('다섯 종류를 화면 기기로', () {
      final ds = t.devices;
      expect(ds.length, 7);
      final ind = dev<InductionDevice>(ds, 'induction-01');
      expect(ind.name, '인덕션');
      expect(ind.burner.level, 5);
      expect(ind.burner.deviceState, BurnerState.on);
      expect(ind.lastControl, Publisher.user);

      final bedLight = dev<LightDevice>(ds, 'light-01');
      expect(bedLight.room, RoomId.bedroom);
      expect(bedLight.name, '침실 조명');
      expect(bedLight.on, isTrue);
      expect(bedLight.brightnessSteps, [0, 20, 100]);
      // 상태를 받지 못한 전등은 is_on 만 본다
      expect(dev<LightDevice>(ds, 'light-00').on, isFalse);

      final fan = dev<FanDevice>(ds, 'fan-01');
      expect(fan.speed, 3);
      expect(fan.auto, isTrue);
      expect(dev<FanDevice>(ds, 'fan-02').online, isFalse);

      final air = dev<AirPurifierDevice>(ds, 'air-01');
      expect(air.mode, AirMode.auto);
      expect(air.airQuality!.level, AirLevel.bad);
      expect(air.airQuality!.pm25, 41.6);

      final water = dev<PurifierDevice>(ds, 'water-01');
      expect(water.lastDispense!.ml, 250);
      expect(water.lastDispense!.auto, isTrue);
    });

    test('필드가 빠지거나 모르는 기기 · 이상한 값', () {
      final ds = BackendTranslator().buildDevices({
        'devices': [
          {'device': 'stove', 'deviceId': 'induction-01'},
          {'device': 'toaster', 'deviceId': 'x-1'},
          {'deviceId': ''},
          {'device': 'fan', 'deviceId': 'fan-9', 'current_state': {'power': 'on', 'speed': 'weird'}},
          {'device': 'air_purifier', 'deviceId': 'air-9', 'current_state': 'broken'},
          'garbage',
        ],
        'appliances': 'nope',
      });
      expect(ds.map((d) => d.id), ['induction-01', 'fan-9', 'air-9']);
      final ind = ds.first as InductionDevice;
      expect(ind.online, isFalse);
      expect(ind.burner.temperature, 25);
      expect((ds[1] as FanDevice).speed, 2);
      expect((ds[2] as AirPurifierDevice).on, isFalse);
    });
  });

  group('실시간 device.state', () {
    test('전등: 켜짐 → 절전(fadeout) → 꺼짐', () {
      var m = t.translate('device.state', 'now', {'deviceId': 'light-00', 'state': {'power': 'on', 'brightness': 100}});
      expect(((m.single as DeviceMsg).device as LightDevice).brightness, 100);
      m = t.translate('device.state', 'now', {'deviceId': 'light-00', 'state': {'power': 'on', 'brightness': 100, 'mode': 'fadeout'}});
      final l = (m.single as DeviceMsg).device as LightDevice;
      expect(l.saving, isTrue);
      expect(l.brightness, 20);
      m = t.translate('device.state', 'now', {'deviceId': 'light-00', 'state': {'power': 'off'}});
      expect(((m.single as DeviceMsg).device as LightDevice).on, isFalse);
    });

    test('화면에서 보낸 명령의 결과는 직접 조작, system 은 자동', () {
      t.rememberCommand('cmd-1');
      var m = t.translate('device.state', 'now', {'deviceId': 'fan-01', 'state': {'power': 'on', 'speed': 'low', 'lastControl': {'commandId': 'cmd-1', 'publisher': 'api'}}});
      var f = (m.single as DeviceMsg).device as FanDevice;
      expect(f.speed, 1);
      expect(f.auto, isFalse);
      m = t.translate('device.state', 'now', {'deviceId': 'fan-01', 'state': {'power': 'off', 'lastControl': {'publisher': 'system'}}});
      f = (m.single as DeviceMsg).device as FanDevice;
      expect(f.on, isFalse);
      expect(f.auto, isTrue);
      expect(f.speed, 1); // 풍량이 없으면 그대로
    });

    test('power 가 없는 상태 · 모르는 기기는 무시', () {
      expect(t.translate('device.state', 'now', {'deviceId': 'fan-01', 'state': {'speed': 'low'}}), isEmpty);
      expect(t.translate('device.state', 'now', {'deviceId': 'nope', 'state': {'power': 'on'}}), isEmpty);
      expect(t.translate('device.state', 'now', {'deviceId': 'fan-01'}), isEmpty);
    });

    test('공기청정기: 기기가 스스로 켬 = 공기질 이유, 모드 전환', () {
      var m = t.translate('device.state', 'now', {
        'deviceId': 'air-01',
        'state': {'power': 'on', 'mode': 'auto', 'airQuality': {'pm25': 80, 'level': 'bad'}, 'lastControl': {'publisher': 'system', 'commandId': 'dev-1'}},
      });
      var a = (m.single as DeviceMsg).device as AirPurifierDevice;
      expect(a.auto, isTrue);
      expect(a.autoReason, AirAutoReason.air);
      m = t.translate('device.state', 'now', {'deviceId': 'air-01', 'state': {'power': 'on', 'mode': 'manual'}});
      a = (m.single as DeviceMsg).device as AirPurifierDevice;
      expect(a.mode, AirMode.manual);
      expect(a.airQuality!.pm25, 80); // 공기질이 없으면 그대로
    });

    test('공기청정기: AI 판단으로 켬 (인덕션 켜짐) = 인덕션 이유, 상태가 먼저 와도', () {
      // 상태 먼저
      t.translate('device.state', 'now', {'deviceId': 'air-01', 'state': {'power': 'on', 'lastControl': {'publisher': 'api', 'commandId': 'cmd-ai'}}});
      final m = t.translate('ai.decision', 'now', {
        'scenario': 'cooking_air',
        'actions': [{'device': 'air_purifier', 'deviceId': 'air-01', 'action': 'on', 'status': 'sent', 'commandId': 'cmd-ai'}],
      });
      final a = (m.single as DeviceMsg).device as AirPurifierDevice;
      expect(a.auto, isTrue);
      expect(a.autoReason, AirAutoReason.induction);
    });

    test('공기청정기: 음성 명령으로 켠 것은 자동이 아님', () {
      t.translate('ai.decision', 'now', {
        'voiceId': 'voice-1',
        'actions': [{'device': 'air_purifier', 'deviceId': 'air-01', 'action': 'on', 'status': 'sent', 'commandId': 'cmd-v'}],
      });
      final m = t.translate('device.state', 'now', {'deviceId': 'air-01', 'state': {'power': 'on', 'lastControl': {'publisher': 'api', 'commandId': 'cmd-v'}}});
      final a = (m.single as DeviceMsg).device as AirPurifierDevice;
      expect(a.auto, isFalse);
      expect(a.autoReason, isNull);
    });

    test('정수기 출수', () {
      final m = t.translate('device.state', '2026-10-26T07:00:00Z', {'deviceId': 'water-01', 'state': {'status': 'dispensing', 'lastDispensedMl': 120}});
      final w = (m.single as DeviceMsg).device as PurifierDevice;
      expect(w.dispensing, isTrue);
      expect(w.lastDispense!.ml, 120);
    });
  });

  group('그 밖의 실시간 메시지', () {
    test('화구 온도 → 기록', () {
      final m = t.translate('burner.telemetry', 'now', {'deviceId': 'induction-01', 'burners': [{'deviceState': 'overheated', 'level': 9, 'temperature': 160}]});
      expect((m.single as BurnerTelemetryMsg).burners.first.deviceState, BurnerState.overheated);
      expect(t.translate('burner.telemetry', 'now', {'deviceId': 'induction-01', 'burners': []}), isEmpty);
    });

    test('재실 판단 → 위치 + 기록', () {
      final m = t.translate('sensing.result', 'now', {'observedAt': '2026-10-26T10:00:00Z', 'room': 'room', 'present': true, 'confidence': 0.8});
      expect((m[0] as LocationMsg).location, Location.bedroom);
      expect((m[1] as SensingMsg).sample.confidence, 0.8);
    });

    test('command.result 실패만', () {
      expect(t.translate('command.result', 'now', {'deviceId': 'fan-01', 'status': 'acked'}), isEmpty);
      final m = t.translate('command.result', 'now', {'deviceId': 'fan-01', 'commandId': 'c', 'status': 'failed'});
      expect((m.single as CommandFailedMsg).deviceName, '주방 환풍기');
    });

    test('안내 문장: voiceId 가 있는 ai.announcement 는 건너뜀', () {
      expect(t.translate('ai.announcement', 'now', {'text': '조명을 켰어요', 'voiceId': 'v1'}), isEmpty);
      expect(t.translate('ai.announcement', 'now', {'text': '   '}), isEmpty);
      final m = t.translate('weather.briefing', 'now', {'text': '오후에 비가 와요', 'decisionId': 'd1'});
      expect((m.single as AnnouncementMsg).text, '오후에 비가 와요');
      final a = t.translate('ai.announcement', 'now', {'text': '외출 중이라 모두 껐어요', 'decisionId': 'd2'});
      expect((a.single as AnnouncementMsg).id, 'ai.announcement:d2');
    });

    test('voice.status · 모르는 이벤트', () {
      final m = t.translate('voice.status', 'now', {'voiceId': 'v1', 'status': 'thinking'});
      expect((m.single as VoiceMsg).record.status, VoiceStatus.thinking);
      expect(t.translate('mystery.event', 'now', {'a': 1}), isEmpty);
    });

    test('기기 온라인 변경만 알림 (GET /devices)', () {
      final m = t.connectionChanges({
        'items': [
          {'deviceId': 'fan-02', 'online': true},
          {'deviceId': 'fan-01', 'online': true},
          {'deviceId': 'ghost', 'online': false},
        ],
      });
      expect(m.length, 1);
      expect((m.single as ConnectionMsg).deviceId, 'fan-02');
      expect(t.connectionChanges('garbage'), isEmpty);
    });
  });

  test('밝기 → 가까운 전등 단계 (동률이면 100 쪽)', () {
    expect(nearestLightStep(0), 0);
    expect(nearestLightStep(9), 0);
    expect(nearestLightStep(10), 0);
    expect(nearestLightStep(15), 20);
    expect(nearestLightStep(60), 100);
    expect(nearestLightStep(100), 100);
  });

  test('센서 노드 (GET /sensing/combined)', () {
    final now = DateTime.fromMillisecondsSinceEpoch(1000000 * 1000);
    final nodes = parseSensingNodes({
      'locations': {
        'kitchen': {'node': {'node': 'r2', 'status': 'ok', 't_end': 999998, 'quality': {'rssi': -52.4, 'rate_hz': 9.8}}},
        'room': {'node': {'node': 'r1', 'status': 'ok', 't_end': 999000, 'quality': {'rssi': -60}}},
        'toilet': {'node': {'node': '<script>', 'status': 'calibrating'}},
      },
    }, now);
    expect(nodes.map((n) => n.room), [HouseRoom.kitchen, HouseRoom.bedroom, HouseRoom.bathroom]);
    expect(nodes[0].status, NodeStatus.ok);
    expect(nodes[0].rssi, -52.4);
    expect(nodes[0].rateHz, 9.8);
    expect(nodes[1].status, NodeStatus.stale); // 10초 넘게 지난 메시지
    expect(nodes[1].rssi, isNull);
    expect(nodes[2].status, NodeStatus.other);
    expect(nodes[2].node, 'r3'); // 이상한 이름은 기본 이름
    final empty = parseSensingNodes(null, now);
    expect(empty.every((n) => n.status == NodeStatus.missing), isTrue);
  });
}
