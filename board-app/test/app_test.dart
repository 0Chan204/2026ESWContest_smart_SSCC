import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:homevis_gui/app/app.dart';
import 'package:homevis_gui/data/home_source.dart';
import 'package:homevis_gui/models/types.dart';
import 'package:homevis_gui/store/preferences.dart';

import 'fakes.dart';

/// 화면 전체 흐름: 연결 → 각 탭 → 시트. 넘침(RenderFlex overflow) 같은 그리기 오류가 나면 실패한다.
Future<FakeBackend> pumpApp(WidgetTester tester, {required Size size, AppMode mode = AppMode.normal, FakeBackend? backend}) async {
  final be = backend ?? FakeBackend();
  tester.view.physicalSize = size;
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
  await tester.pumpWidget(HomeVisApp(
    source: HomeSource(client: be.client, apiBase: 'http://127.0.0.1:8000', channelFactory: be.channel),
    preferences: Preferences(mode: mode),
  ));
  await tester.pump(const Duration(milliseconds: 100));
  await tester.pump(const Duration(milliseconds: 100));
  return be;
}

Future<void> unmount(WidgetTester tester) async {
  await tester.pumpWidget(const SizedBox.shrink());
  await tester.pump(const Duration(seconds: 1));
}

Future<void> tapText(WidgetTester tester, String text) async {
  await tester.tap(find.text(text).first);
  await tester.pump(const Duration(milliseconds: 300));
  await tester.pump(const Duration(milliseconds: 300));
}

void expectPost((String, Object?) got, String path, Object? body) {
  expect(got.$1, path);
  expect(got.$2, body);
}

void main() {
  for (final size in const [Size(1280, 720), Size(1920, 1080), Size(1024, 600)]) {
    for (final mode in AppMode.values) {
      testWidgets('모든 탭 · ${mode.name} · ${size.width.toInt()}×${size.height.toInt()}', (tester) async {
        final be = await pumpApp(tester, size: size, mode: mode);
        expect(find.text('우리 집'), findsWidgets);
        // 기록에 자동 차단(e-new)이 있어도 안내 시트는 실시간 메시지로만 뜬다
        for (final tab in ['주방', '욕실', mode == AppMode.elderly ? '안전 기록' : '기록', '설정', '홈']) {
          await tapText(tester, tab);
        }
        // 위치 크게 보기
        await tapText(tester, mode == AppMode.elderly ? '지금 위치' : '크게 보기');
        expect(find.text('각 공간의 Wi-Fi 신호로 판단해요. 카메라는 쓰지 않아요.'), size.height <= 760 && mode == AppMode.elderly ? findsNothing : findsOneWidget);
        await tester.pump(const Duration(seconds: 3));
        await tester.tap(find.bySemanticsLabel('닫기').last);
        await tester.pump(const Duration(milliseconds: 400));

        // 실시간: 낙상 경보 (본인 응답 대기 단계)
        be.channels.last.push('fall.incident', {
          'incidentId': 'f1',
          'room': 'toilet',
          'status': 'pending',
          'detectedAt': DateTime.now().toUtc().toIso8601String(),
          'autoReportAt': DateTime.now().add(const Duration(seconds: 60)).toUtc().toIso8601String(),
          'stage': 'user',
          'guardianAlertAt': DateTime.now().add(const Duration(seconds: 30)).toUtc().toIso8601String(),
          'confidence': 0.93,
        });
        await tester.pump(const Duration(milliseconds: 100));
        expect(find.text('욕실 낙상 감지'), findsWidgets);
        await tapText(tester, '확인했어요');

        // 실시간: 음성 확인 창
        be.channels.last.push('voice.status', {
          'voiceId': 'v1',
          'status': 'confirm_required',
          'text': '욕실 조명 켜줘',
          'confirmText': '욕실 조명을 켤까요?',
          'confirmDeadline': DateTime.now().add(const Duration(seconds: 30)).toUtc().toIso8601String(),
        });
        await tester.pump(const Duration(milliseconds: 100));
        expect(find.text('욕실 조명을 켤까요?'), findsOneWidget);
        await tapText(tester, '실행');
        expectPost(be.posts.last, '/voice/commands/v1/confirm', {'approved': true});

        // 실시간: 안전 조치 안내 시트
        be.channels.last.push('safety.event', {
          'eventId': 'evt-live',
          'type': 'auto_power_reduced',
          'severity': 'warning',
          'occurredAt': DateTime.now().toUtc().toIso8601String(),
          'room': 'kitchen',
          'guidance': '주방을 오래 비우셔서 화력을 낮췄어요.',
          'trigger': '부재 3분',
          'action': '화력 1단',
        });
        await tester.pump(const Duration(milliseconds: 100));
        expect(find.text('인덕션 화력 자동 저감'), findsWidgets);
        await tapText(tester, '확인');
        await unmount(tester);
      });
    }
  }

  testWidgets('기기 카드 스위치 · 상세 시트', (tester) async {
    final be = await pumpApp(tester, size: const Size(1280, 720));
    await tester.tap(find.bySemanticsLabel(RegExp('^공기청정기 자세히')));
    await tester.pump(const Duration(milliseconds: 400));
    expect(find.text('운전 모드'), findsOneWidget);
    await tapText(tester, '수동');
    expectPost(be.posts.last, '/devices/air-01/commands', {'type': 'set_mode', 'mode': 'manual'});
    await tester.tap(find.bySemanticsLabel('닫기').last);
    await tester.pump(const Duration(milliseconds: 400));
    await tester.tap(find.bySemanticsLabel('주방 환풍기 끄기'));
    await tester.pump(const Duration(milliseconds: 100));
    expectPost(be.posts.last, '/devices/fan-01/commands', {'type': 'off'});
    await unmount(tester);
  });

  testWidgets('처음 연결 실패 → 다시 시도', (tester) async {
    final be = FakeBackend(failSnapshot: true);
    await pumpApp(tester, size: const Size(1280, 720), backend: be);
    expect(find.text('서버에 연결하지 못했어요'), findsOneWidget);
    be.failSnapshot = false;
    await tapText(tester, '다시 시도');
    await tester.pump(const Duration(milliseconds: 200));
    expect(find.text('우리 집'), findsWidgets);
    await unmount(tester);
  });

  testWidgets('설정: 다크 · 어르신 전환', (tester) async {
    await pumpApp(tester, size: const Size(1280, 720));
    await tapText(tester, '설정');
    await tapText(tester, '다크');
    await tapText(tester, '어르신');
    expect(find.text('글자 크기'), findsOneWidget);
    await tapText(tester, '정보');
    expect(find.text('HomeVIS 7.0 · board'), findsOneWidget);
    await tapText(tester, '홈');
    await unmount(tester);
  });
}
