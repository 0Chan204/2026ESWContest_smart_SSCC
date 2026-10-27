// v7: 첫 실행(모드 선택 · 권한 동의) · 키패드 연락처 등록 · 보드 마이크 · 음성 설정 · 주방 전등(light-02)
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:homevis_gui/app/app.dart';
import 'package:homevis_gui/data/home_source.dart';
import 'package:homevis_gui/features/home/home_map.dart';
import 'package:homevis_gui/models/types.dart';
import 'package:homevis_gui/store/home_state.dart';
import 'package:homevis_gui/store/preferences.dart';
import 'package:homevis_gui/store/prefs_storage.dart';
import 'package:homevis_gui/store/speaker.dart';

import 'fakes.dart';
import 'fixtures.dart';

Future<FakeBackend> pump(
  WidgetTester tester, {
  Size size = const Size(1280, 720),
  FakeBackend? backend,
  Preferences? prefs,
  Speaker speaker = const SilentSpeaker(),
}) async {
  final be = backend ?? FakeBackend();
  tester.view.physicalSize = size;
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
  await tester.pumpWidget(HomeVisApp(
    source: HomeSource(client: be.client, apiBase: 'http://127.0.0.1:8000', channelFactory: be.channel),
    preferences: prefs ?? Preferences(mode: AppMode.normal),
    speaker: speaker,
  ));
  await tester.pump(const Duration(milliseconds: 100));
  await tester.pump(const Duration(milliseconds: 100));
  return be;
}

Future<void> settle(WidgetTester tester) async {
  await tester.pump(const Duration(milliseconds: 300));
  await tester.pump(const Duration(milliseconds: 300));
}

Future<void> tapText(WidgetTester tester, String text) async {
  await tester.tap(find.text(text).last);
  await settle(tester);
}

/// 왼쪽 레일 (화면에서 가장 먼저 그려진 같은 글자)
Future<void> tapNav(WidgetTester tester, String text) async {
  await tester.tap(find.text(text).first);
  await settle(tester);
}

/// 키패드 위 번호 표시
Finder shown(String formatted) => find.bySemanticsLabel('입력한 번호 $formatted');

Future<void> tapLabel(WidgetTester tester, Pattern label) async {
  await tester.tap(find.bySemanticsLabel(label).last);
  await settle(tester);
}

void expectReq((String, Object?) got, String path, Object? body) {
  expect(got.$1, path);
  expect(got.$2, body);
}

Future<void> unmount(WidgetTester tester) async {
  await tester.pumpWidget(const SizedBox.shrink());
  await tester.pump(const Duration(seconds: 4));
}

Future<void> keypad(WidgetTester tester, String digits) async {
  for (final d in digits.split('')) {
    await tester.tap(find.bySemanticsLabel(d).last);
    await tester.pump(const Duration(milliseconds: 50));
  }
}

class RecordingSpeaker implements Speaker {
  final said = <String?>[];
  @override
  void speak(String? text) => said.add(text);
}

void main() {
  group('첫 실행', () {
    for (final size in const [Size(1280, 720), Size(1920, 1080), Size(1024, 600)]) {
      testWidgets('모드 선택 → 권한 동의(닫히지 않음) → 홈, 저장 · ${size.width.toInt()}×${size.height.toInt()}', (tester) async {
        final storage = MemoryPrefsStorage();
        final prefs = Preferences.load(storage);
        await pump(tester, size: size, prefs: prefs);
        expect(find.text('어떤 화면이 편하세요?'), findsOneWidget);
        expect(find.text('우리 집'), findsNothing);
        await tapText(tester, '크게 보기');
        expect(prefs.elderly, isTrue);
        expect(prefs.modeChosen, isTrue);
        // 동의 창: 바깥을 눌러도 닫히지 않는다
        expect(find.text('HomeVIS 권한'), findsOneWidget);
        expect(find.textContaining('재실 감지', findRichText: true), findsOneWidget);
        await tester.tapAt(const Offset(5, 5));
        await settle(tester);
        expect(find.text('HomeVIS 권한'), findsOneWidget);
        await tapText(tester, '허용');
        expect(find.text('HomeVIS 권한'), findsNothing);
        expect(prefs.consentAnswered, isTrue);
        expect(prefs.voiceCommands, isTrue);
        expect(prefs.readAloud, isTrue);
        expect(find.text('우리 집'), findsWidgets);
        expect(find.bySemanticsLabel('음성으로 말하기'), findsOneWidget); // 허용 → 마이크 버튼
        // 다시 켜면 바로 홈
        final again = Preferences.load(storage);
        expect(again.modeChosen && again.consentAnswered && again.elderly, isTrue);
        await unmount(tester);
      });
    }

    testWidgets('허용 안 함 → 마이크 버튼 없음, 설정 > 앱 권한에서 켜기', (tester) async {
      final prefs = Preferences(onboarded: false);
      await pump(tester, prefs: prefs);
      await tapText(tester, '기본 보기');
      await tapText(tester, '허용 안 함');
      expect(prefs.voiceCommands, isFalse);
      expect(find.bySemanticsLabel('음성으로 말하기'), findsNothing);
      await tapNav(tester, '설정');
      await tapText(tester, '앱 권한');
      expect(find.text('항상 사용'), findsOneWidget);
      await tapLabel(tester, '마이크');
      expect(prefs.voiceCommands, isTrue);
      expect(find.bySemanticsLabel('음성으로 말하기'), findsOneWidget);
      // 설정 > 화면 모드에서 바꿀 수 있다
      await tapText(tester, '화면');
      await tapText(tester, '어르신');
      expect(prefs.elderly, isTrue);
      await unmount(tester);
    });

    testWidgets('읽어 주기를 끄면 Speaker 로 가지 않는다', (tester) async {
      final speaker = RecordingSpeaker();
      final prefs = Preferences(mode: AppMode.normal, readAloud: false);
      final be = await pump(tester, prefs: prefs, speaker: speaker);
      be.channels.last.push('ai.announcement', {'decisionId': 'd1', 'text': '창문을 열어 주세요'});
      await settle(tester);
      expect(speaker.said, isEmpty);
      prefs.setReadAloud(true);
      be.channels.last.push('ai.announcement', {'decisionId': 'd2', 'text': '환기할게요'});
      await settle(tester);
      expect(speaker.said, ['환기할게요']);
      await unmount(tester);
    });
  });

  group('연락처 등록 (키패드)', () {
    for (final mode in AppMode.values) {
      testWidgets('홈 "보호자 · 등록 필요" → 관계 → 키패드 → 저장 → 가린 번호 · ${mode.name}', (tester) async {
        final be = FakeBackend(guardian: null);
        await pump(tester, backend: be, prefs: Preferences(mode: mode));
        await tapText(tester, mode == AppMode.elderly ? '등록해 주세요' : '등록 필요');
        expect(find.text('어떤 분인가요?'), findsOneWidget);
        for (final r in ['보호자', '아들', '딸', '배우자', '손주', '이웃']) {
          expect(find.bySemanticsLabel(r), findsWidgets);
        }
        await tapLabel(tester, '아들');
        expect(find.text('아들님 휴대폰 번호를 눌러 주세요'), findsOneWidget);
        expect(shown('010'), findsOneWidget);
        // 짧으면 저장하지 않고 시트에 머문다
        await keypad(tester, '1234');
        expect(shown('010-1234'), findsOneWidget);
        await tapText(tester, '저장');
        expect(find.text('번호를 끝까지 눌러 주세요.'), findsOneWidget);
        expect(be.puts, isEmpty);
        await keypad(tester, '56789'); // 11자리 넘는 9 는 무시
        expect(shown('010-1234-5678'), findsOneWidget);
        await tapLabel(tester, '지우기');
        expect(shown('010-1234-567'), findsOneWidget);
        await keypad(tester, '8');
        await tapText(tester, '저장');
        expectReq(be.puts.last, '/guardian', {'name': '아들', 'phone': '01012345678'});
        expect(find.text('저장했어요. (확인 문자는 보내지 않았어요)'), findsOneWidget);
        expect(find.text('어떤 분인가요?'), findsNothing);
        // 홈 상태가 바뀐다
        expect(find.text('아들'), findsWidgets);
        await tapNav(tester, '설정');
        await tapText(tester, '비상 연락처');
        expect(find.text('010-****-5678'), findsOneWidget);
        await unmount(tester);
      });
    }

    testWidgets('본인: 이름 고정 · 확인 문자 보냄 · 서버 오류는 시트에 짧게', (tester) async {
      final be = FakeBackend()..verificationSent = true;
      await pump(tester, backend: be);
      await tapNav(tester, '설정');
      await tapText(tester, '비상 연락처');
      expect(find.text('010-****-5678'), findsOneWidget); // 등록된 보호자
      await tapText(tester, '등록'); // 본인은 아직 없음
      expect(find.text('본인 휴대폰 번호를 눌러 주세요'), findsOneWidget);
      await keypad(tester, '00001111');
      be.putStatus = 500;
      await tapText(tester, '저장');
      expect(find.text('저장하지 못했어요. 잠시 후 다시 해 주세요.'), findsOneWidget);
      expect(find.text('본인 휴대폰 번호를 눌러 주세요'), findsOneWidget);
      be.putStatus = 422;
      await tapText(tester, '저장');
      expect(find.text('번호 형식을 확인해 주세요.'), findsOneWidget);
      be.putStatus = 200;
      await tapText(tester, '저장');
      expectReq(be.puts.last, '/user', {'name': '본인', 'phone': '01000001111'});
      expect(find.text('저장했어요. 확인 문자를 보냈어요.'), findsOneWidget);
      expect(find.text('010-****-1111'), findsOneWidget);
      // 변경: 보호자 → 관계 다시 고르기, 이전 버튼
      await tester.tap(find.text('변경').first);
      await settle(tester);
      await tapLabel(tester, '배우자');
      await tapText(tester, '이전');
      expect(find.text('어떤 분인가요?'), findsOneWidget);
      await tapText(tester, '취소');
      expect(find.text('어떤 분인가요?'), findsNothing);
      await unmount(tester);
    });

    testWidgets('어르신 큰 글씨(130%) · 1024×600 에서도 키패드 시트가 넘치지 않는다', (tester) async {
      final prefs = Preferences(mode: AppMode.elderly)..setFontScale(130);
      await pump(tester, size: const Size(1024, 600), prefs: prefs, backend: FakeBackend(guardian: null));
      await tapText(tester, '등록해 주세요');
      await tapLabel(tester, '손주');
      await keypad(tester, '12345678');
      expect(shown('010-1234-5678'), findsOneWidget);
      await unmount(tester);
    });
  });

  group('보드 마이크', () {
    testWidgets('지금 백엔드(엔드포인트 없음) → "쓸 수 없어요" 잠깐, 재시도 없음', (tester) async {
      final be = await pump(tester, prefs: Preferences(mode: AppMode.normal, voiceCommands: true));
      await tapLabel(tester, '음성으로 말하기');
      expect(be.posts.where((p) => p.$1 == '/voice/listen').length, 1);
      expect(find.text('지금은 음성 명령을 쓸 수 없어요'), findsOneWidget);
      await tester.pump(const Duration(seconds: 4));
      expect(find.text('지금은 음성 명령을 쓸 수 없어요'), findsNothing);
      expect(be.posts.where((p) => p.$1 == '/voice/listen').length, 1);
      await unmount(tester);
    });

    testWidgets('제안 계약: listen → WS listening/recognizing → 닫으면 cancel', (tester) async {
      final be = FakeBackend()..voiceListen = true;
      await pump(tester, backend: be, prefs: Preferences(mode: AppMode.elderly, voiceCommands: true));
      await tapLabel(tester, '음성으로 말하기');
      expect(find.text('듣고 있어요'), findsOneWidget);
      expect(find.text('욕실 조명 켜줘'), findsOneWidget); // 예시
      be.channels.last.push('voice.status', {'voiceId': 'listen-1', 'status': 'recognizing', 'text': '주방 불 켜', 'source': 'button'});
      await settle(tester);
      expect(find.text('알아듣는 중…'), findsOneWidget);
      expect(find.text('“주방 불 켜”'), findsOneWidget);
      await tapLabel(tester, '닫기');
      expectReq(be.posts.last, '/voice/listen/cancel', {'voiceId': 'listen-1'});
      await unmount(tester);
    });

    testWidgets('음성 명령을 끄면 마이크 버튼이 없다 · 호출어 대기는 WS voice.settings 로 표시', (tester) async {
      final be = await pump(tester);
      expect(find.bySemanticsLabel('음성으로 말하기'), findsNothing);
      be.channels.last.push('voice.settings', {'wakeWord': true, 'standby': true});
      await settle(tester);
      expect(find.text('호출어 대기'), findsOneWidget); // 음성 명령이 꺼져 있어도 마이크가 켜져 있음을 알린다
      be.channels.last.push('voice.settings', {'wakeWord': false, 'standby': false});
      await settle(tester);
      expect(find.text('호출어 대기'), findsNothing);
      await unmount(tester);
    });

    testWidgets('호출어(source: wakeword) voice.status 는 패널을 저절로 연다', (tester) async {
      final be = await pump(tester, prefs: Preferences(mode: AppMode.normal, voiceCommands: true));
      be.channels.last.push('voice.status', {'voiceId': 'wk-1', 'status': 'listening', 'source': 'wakeword'});
      await settle(tester);
      expect(find.text('음성 명령 · 호출어'), findsOneWidget);
      expect(find.text('듣고 있어요'), findsOneWidget);
      be.channels.last.push('voice.status', {'voiceId': 'wk-1', 'status': 'failed', 'reason': 'no_speech'});
      await settle(tester);
      expect(find.text('말씀이 들리지 않았어요'), findsOneWidget);
      await unmount(tester);
    });

    testWidgets('확인 창 409 → 오류 토스트 없이 닫힘', (tester) async {
      final be = await pump(tester);
      be.channels.last.push('voice.status', {
        'voiceId': 'race',
        'status': 'confirm_required',
        'confirmText': '주방 조명을 켤까요?',
        'confirmDeadline': DateTime.now().add(const Duration(seconds: 30)).toUtc().toIso8601String(),
      });
      await settle(tester);
      be.confirmStatus = 409;
      await tapText(tester, '실행');
      expect(find.text('주방 조명을 켤까요?'), findsNothing);
      expect(find.text('지금은 음성 명령을 쓸 수 없어요'), findsNothing);
      expect(find.text('지금 상태에서는 할 수 없는 동작이에요.'), findsNothing);
      await unmount(tester);
    });
  });

  group('설정 > 음성', () {
    testWidgets('음성 설정 엔드포인트가 없으면 호출어 끔 + 한 줄 안내', (tester) async {
      await pump(tester, prefs: Preferences(mode: AppMode.normal, voiceCommands: true));
      await tapNav(tester, '설정');
      await tapText(tester, '음성');
      expect(find.text('보드 음성 연결 후 사용할 수 있어요'), findsOneWidget);
      expect(find.text('호출어로 부르기 (홈비스)'), findsOneWidget);
      expect(find.text('위험 알림 음성 안내'), findsOneWidget);
      await unmount(tester);
    });

    testWidgets('있으면 GET 으로 읽고 PUT 으로 켬, 음성 명령을 끄면 호출어도 끔', (tester) async {
      final be = FakeBackend()..voiceSettings = {'wakeWord': false, 'standby': false};
      final prefs = Preferences(mode: AppMode.normal, voiceCommands: true);
      await pump(tester, backend: be, prefs: prefs);
      await tapNav(tester, '설정');
      await tapText(tester, '음성');
      expect(find.text('보드 음성 연결 후 사용할 수 있어요'), findsNothing);
      await tapLabel(tester, '호출어로 부르기');
      expectReq(be.puts.last, '/voice/settings', {'wakeWord': true});
      expect(find.text('지금 호출어를 기다리고 있어요'), findsOneWidget);
      expect(find.text('호출어 대기'), findsOneWidget);
      await tapLabel(tester, '음성 명령 사용');
      expect(prefs.voiceCommands, isFalse);
      expectReq(be.puts.last, '/voice/settings', {'wakeWord': false});
      expect(find.text('호출어 대기'), findsNothing);
      await unmount(tester);
    });
  });

  group('주방 전등 light-02 (백엔드 v0.8)', () {
    test('공간으로만 묶는다 (기기 ID 를 적어 두지 않음)', () {
      final source = HomeSource(client: FakeBackend().client);
      final devices = source.translator.buildDevices(snapshotJson());
      final kitchenLight = devices.whereType<LightDevice>().firstWhere((d) => d.id == 'light-02');
      expect(kitchenLight.room, RoomId.kitchen);
      expect(kitchenLight.name, '주방 조명');
      // 다른 ID 라도 공간이 kitchen 이면 주방 칸에
      final json = snapshotJson();
      (json['devices'] as List).add({'device': 'light', 'deviceId': 'lamp-xyz', 'room': 'kitchen', 'online': true, 'is_on': true});
      final state = HomeState.initial().copyWith(devices: source.translator.buildDevices(json));
      final kitchen = roomsOf(state).firstWhere((r) => r.id == HouseRoom.kitchen);
      expect(kitchen.lights.map((l) => l.id), ['light-02', 'lamp-xyz']);
      expect(roomsOf(state).firstWhere((r) => r.id == HouseRoom.bathroom).lights.map((l) => l.id), ['light-00']);
    });

    for (final mode in AppMode.values) {
      testWidgets('평면도 전구 · 주방 타일 · 크게 보기 조절 · ${mode.name}', (tester) async {
        final be = await pump(tester, prefs: Preferences(mode: mode));
        if (mode == AppMode.normal) {
          await tapLabel(tester, RegExp('^주방 조명 꺼짐 · 켜기'));
          expectReq(be.posts.last, '/devices/light-02/commands', {'type': 'on'});
          be.channels.last.push('device.state', {'deviceId': 'light-02', 'state': {'power': 'on', 'brightness': 100}});
          await settle(tester);
          expect(find.bySemanticsLabel(RegExp('^주방 조명 .*끄기')), findsWidgets);
        }
        await tapText(tester, mode == AppMode.elderly ? '지금 위치' : '크게 보기');
        await tester.pump(const Duration(seconds: 1));
        // 주방 칸에도 조명 조작이 있다 (일반 = 밝기 슬라이더 · 어르신 = 큰 스위치)
        expect(find.text('조명'), findsNWidgets(mode == AppMode.elderly ? 3 : 3));
        await tapLabel(tester, '닫기');
        await tapNav(tester, '주방');
        expect(find.text('주방 조명'), findsOneWidget);
        await tester.tap(find.text('주방 조명'));
        await settle(tester);
        expect(be.posts.last.$1, '/devices/light-02/commands');
        await unmount(tester);
      });
    }
  });
}
