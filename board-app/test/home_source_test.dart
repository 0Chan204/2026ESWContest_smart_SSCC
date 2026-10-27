import 'package:flutter_test/flutter_test.dart';
import 'package:homevis_gui/config.dart';
import 'package:homevis_gui/data/home_source.dart';
import 'package:homevis_gui/data/stream_message.dart';
import 'package:homevis_gui/models/types.dart';

import 'fakes.dart';

void expectPost((String, Object?) got, String path, Object? body) {
  expect(got.$1, path);
  expect(got.$2, body);
}

void main() {
  late FakeBackend be;
  late HomeSource source;
  setUp(() {
    be = FakeBackend();
    source = HomeSource(client: be.client, apiBase: 'http://127.0.0.1:8000', channelFactory: be.channel);
  });

  test('주소 만들기 (끝의 / 무시, ws · wss, since)', () {
    expect(apiRoot('http://127.0.0.1:8000/'), 'http://127.0.0.1:8000/api/v1');
    expect(streamUri(raw: 'http://127.0.0.1:8000').toString(), 'ws://127.0.0.1:8000/api/v1/stream');
    expect(streamUri(raw: 'https://example.test', since: 'evt-9').toString(), 'wss://example.test/api/v1/stream?since=evt-9');
    expect(defaultMode('elderly'), AppMode.elderly);
    expect(defaultMode('anything'), AppMode.normal);
    expect(canvasScale('1.5'), 1.5);
    expect(canvasScale('abc'), 0);
  });

  test('처음 불러오기: 기기 · 기록(최신이 앞) · 지난 세션 · 연락처(404 = 없음) · 위치', () async {
    final s = await source.loadSnapshot();
    expect(s.devices.length, 8); // v0.8: 주방 전등 light-02 포함
    expect(s.events.map((e) => e.eventId), ['e-new', 'e-fall', 'e-old']);
    expect(s.sessions.map((x) => x.sessionId), containsAll(['sess-1', 'sess-0']));
    expect(s.contacts.user, isNull);
    expect(s.contacts.guardian!.name, '김보호');
    expect(s.location, Location.kitchen);
    expect(s.sensing.single.activity, 'standing');
    expect(s.kitchenPresence.present, isTrue);
  });

  test('처음 불러오기 실패는 화면에 보여줄 오류', () async {
    be.failSnapshot = true;
    expect(source.loadSnapshot(), throwsA(isA<ApiError>().having((e) => e.status, 'status', 503)));
  });

  group('기기 제어 (POST /devices/{id}/commands)', () {
    setUp(() async => source.loadSnapshot());

    test('꺼진 전등을 절전으로: on 다음 fadeout', () async {
      await source.controlDevice('light-00', const DeviceControl(brightness: 20));
      expect(be.posts.map((p) => p.$2), [
        {'type': 'on'},
        {'type': 'fadeout'},
      ]);
      expect(be.posts.first.$1, '/devices/light-00/commands');
    });

    test('켜진 전등 밝기 100 → on, 0 → off, 켜기 · 끄기', () async {
      await source.controlDevice('light-01', const DeviceControl(brightness: 100));
      await source.controlDevice('light-01', const DeviceControl(brightness: 5));
      await source.controlDevice('light-01', const DeviceControl(brightness: 20));
      await source.controlDevice('light-01', const DeviceControl(on: false));
      expect(be.posts.map((p) => p.$2), [
        {'type': 'on'},
        {'type': 'off'},
        {'type': 'fadeout'},
        {'type': 'off'},
      ]);
    });

    test('환풍기 풍량 · 공기청정기 모드 · 전원', () async {
      await source.controlDevice('fan-01', const DeviceControl(speed: 1));
      await source.controlDevice('fan-01', const DeviceControl(on: true));
      await source.controlDevice('air-01', const DeviceControl(mode: AirMode.manual));
      await source.controlDevice('air-01', const DeviceControl(on: false));
      expect(be.posts.map((p) => p.$2), [
        {'type': 'set_speed', 'speed': 'low'},
        {'type': 'on'},
        {'type': 'set_mode', 'mode': 'manual'},
        {'type': 'off'},
      ]);
      // 보낸 명령 id 를 기억해 결과를 '직접 조작'으로 본다
      expect(source.translator.sentCommands, contains('cmd-1'));
    });

    test('인덕션 · 정수기 · 모르는 기기는 제어하지 않는다', () async {
      expect(source.controlDevice('induction-01', const DeviceControl(on: false)), throwsA(isA<ApiError>()));
      expect(source.controlDevice('water-01', const DeviceControl(on: true)), throwsA(isA<ApiError>()));
      expect(source.controlDevice('ghost', const DeviceControl(on: true)), throwsA(isA<ApiError>()));
      await Future<void>.delayed(Duration.zero);
      expect(be.posts, isEmpty);
    });
  });

  test('음성: 보내기 · 확인', () async {
    final id = await source.voice.send('  욕실 조명 켜줘 ', confidence: 0.9);
    expect(id, 'voice-1');
    await source.voice.confirm('voice-1', true);
    expectPost(be.posts[0], '/voice/commands', {'text': '욕실 조명 켜줘', 'lang': 'ko-KR', 'source': 'voice', 'confidence': 0.9});
    expectPost(be.posts[1], '/voice/commands/voice-1/confirm', {'approved': true});
  });

  test('피드백', () async {
    final fb = await source.submitFeedback('e-new', Verdict.rejected);
    expect(fb.verdict, Verdict.rejected);
    expectPost(be.posts.single, '/safety-events/e-new/feedback', {'verdict': 'rejected'});
  });

  test('실시간: 메시지 받기, 끊기면 since 로 다시 연결', () async {
    await source.loadSnapshot();
    final got = <StreamMessage>[];
    final states = <bool>[];
    final stop = source.subscribe(got.add, onConnection: states.add);
    await Future<void>.delayed(Duration.zero);
    final ch = be.channels.single;
    expect(ch.uri.queryParameters, isEmpty);
    ch.push('device.state', {'deviceId': 'fan-01', 'state': {'power': 'off'}});
    ch.push('safety.event', {'eventId': 'evt-7', 'type': 'absence_detected', 'occurredAt': '2026-10-26T10:00:00Z', 'room': 'kitchen'});
    ch.controller.add('not json');
    ch.controller.add('{"event": "device.state"}');
    await Future<void>.delayed(Duration.zero);
    expect(got.whereType<DeviceMsg>().single.device.id, 'fan-01');
    expect(got.whereType<SafetyEventMsg>().single.event.eventId, 'evt-7');
    expect(states, [true]);
    await ch.controller.close();
    await Future<void>.delayed(const Duration(milliseconds: 1200));
    expect(be.channels.length, 2);
    expect(be.channels.last.uri.queryParameters['since'], 'evt-7');
    expect(states, [true, false, true]);
    stop();
  });

  test('센서 노드 · 날씨', () async {
    final nodes = await source.loadSensingNodes();
    expect(nodes.first.rssi, -50);
    final w = await source.loadWeather();
    expect(w!.location, '서울');
    expect(w.hourly, isNotEmpty);
  });

  test('서버가 꺼져 있으면 연결 오류', () async {
    final down = HomeSource(client: FakeDownClient(), apiBase: 'http://127.0.0.1:9');
    expect(down.loadSnapshot(), throwsA(isA<ApiError>()));
  });
}
