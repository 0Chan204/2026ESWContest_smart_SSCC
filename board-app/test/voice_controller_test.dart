import 'dart:async';

import 'package:flutter_test/flutter_test.dart';
import 'package:homevis_gui/data/home_source.dart';
import 'package:homevis_gui/features/voice/voice_controller.dart';
import 'package:homevis_gui/models/types.dart';
import 'package:homevis_gui/store/speaker.dart';

/// 음성 창구 흉내. listenResult / settings 로 서버 응답을 정한다
class FakeConfirmer implements VoiceApi {
  final calls = <(String, bool)>[];
  final cancels = <String>[];
  int listens = 0;
  Object? confirmError;

  /// null 이면 404 (아직 없는 기능)
  FutureOr<ListenStart> Function()? listenResult;
  VoiceSettings? settings;
  bool settingsMissing = true;
  final saved = <bool>[];

  @override
  Future<void> confirm(String voiceId, bool approved) async {
    calls.add((voiceId, approved));
    if (confirmError != null) throw confirmError!;
  }

  @override
  Future<ListenStart> listen() async {
    listens++;
    final r = listenResult;
    if (r == null) throw const ApiError('찾을 수 없어요.', 404);
    return r();
  }

  @override
  Future<void> cancelListen(String voiceId) async {
    cancels.add(voiceId);
    throw const ApiError('찾을 수 없어요.', 404); // 오류는 무시돼야 한다
  }

  @override
  Future<VoiceSettings?> loadSettings() async {
    if (settingsMissing) return null;
    return settings;
  }

  @override
  Future<VoiceSettings> saveSettings({required bool wakeWord}) async {
    saved.add(wakeWord);
    if (settingsMissing) throw const ApiError('찾을 수 없어요.', 404);
    return settings = VoiceSettings(wakeWord: wakeWord, standby: wakeWord);
  }
}

class FakeSpeaker implements Speaker {
  final said = <String?>[];
  @override
  void speak(String? text) => said.add(text);
}

void main() {
  late FakeConfirmer confirmer;
  late FakeSpeaker speaker;
  late VoiceController v;

  setUp(() {
    confirmer = FakeConfirmer();
    speaker = FakeSpeaker();
    v = VoiceController.detached(speaker: speaker, api: confirmer);
  });
  tearDown(() => v.dispose());

  VoiceRecord rec(String id, VoiceStatus s,
          {String? text, String? answer, String? confirmText, String? deadline, String? source, String? reason}) =>
      VoiceRecord(
          voiceId: id,
          status: s,
          text: text,
          answer: answer,
          confirmText: confirmText,
          confirmDeadline: deadline,
          source: source,
          reason: reason);

  testWidgets('received → thinking → confirm → 실행 → executed → 저절로 닫힘', (tester) async {
    v.apply(rec('v1', VoiceStatus.received, text: '욕실 조명 켜줘'));
    expect(v.open, isTrue);
    expect(v.phase, VoicePhase.processing);
    expect(v.progress, '알아들었어요');
    expect(v.heard, '욕실 조명 켜줘');
    v.apply(rec('v1', VoiceStatus.thinking));
    expect(v.progress, '확인하고 있어요');
    final deadline = DateTime.now().add(const Duration(seconds: 30)).toUtc().toIso8601String();
    v.apply(rec('v1', VoiceStatus.confirmRequired, confirmText: '욕실 조명을 켤까요?', deadline: deadline));
    expect(v.phase, VoicePhase.confirm);
    expect(v.confirmText, '욕실 조명을 켤까요?');
    v.approve();
    await tester.pump();
    expect(confirmer.calls, [('v1', true)]);
    expect(v.progress, '실행하고 있어요');
    v.apply(rec('v1', VoiceStatus.executed, answer: '욕실 조명을 켤게요.'));
    expect(v.phase, VoicePhase.completed);
    expect(v.reply, '욕실 조명을 켤게요.');
    expect(speaker.said.last, '욕실 조명을 켤게요.');
    await tester.pump(const Duration(seconds: 4));
    expect(v.open, isFalse);
  });

  testWidgets('확인 창에서 취소 = confirm(false)', (tester) async {
    v.apply(rec('v2', VoiceStatus.confirmRequired, confirmText: '환풍기를 끌까요?'));
    v.cancel();
    await tester.pump();
    expect(confirmer.calls, [('v2', false)]);
    expect(v.open, isFalse);
    // 닫은 명령의 늦은 상태는 패널을 다시 열지 않는다
    v.apply(rec('v2', VoiceStatus.cancelled));
    expect(v.open, isFalse);
  });

  testWidgets('answered · cancelled/timeout · failed 문구', (tester) async {
    v.apply(rec('a', VoiceStatus.answered, answer: '오늘은 맑아요.'));
    expect(v.reply, '오늘은 맑아요.');
    v.apply(rec('b', VoiceStatus.timeout));
    expect(v.phase, VoicePhase.error);
    expect(v.errorText, voiceMisheard);
    v.apply(rec('c', VoiceStatus.cancelled));
    expect(v.errorText, '잘 듣지 못했어요');
    v.apply(rec('d', VoiceStatus.failed));
    expect(v.errorText, '지금은 음성 명령을 쓸 수 없어요');
    await tester.pump(const Duration(seconds: 4));
    expect(v.open, isFalse);
  });

  testWidgets('답이 없는 진행 단계는 20초 뒤 실패로 닫힘', (tester) async {
    v.apply(rec('s', VoiceStatus.thinking));
    await tester.pump(const Duration(seconds: 21));
    expect(v.phase, VoicePhase.error);
    await tester.pump(const Duration(seconds: 4));
    expect(v.open, isFalse);
  });

  testWidgets('새 voiceId 가 오면 그 명령으로 바뀐다', (tester) async {
    v.apply(rec('old', VoiceStatus.thinking, text: '하나'));
    v.apply(rec('new', VoiceStatus.received, text: '둘'));
    expect(v.voiceId, 'new');
    expect(v.heard, '둘');
    v.apply(rec('new', VoiceStatus.answered));
    expect(v.reply, '알겠어요.');
    await tester.pump(const Duration(seconds: 4));
  });

  group('보드 마이크 (제안 계약)', () {
    testWidgets('마이크 → 202 → listening → recognizing(text) → received …', (tester) async {
      confirmer.listenResult = () => const ListenStart(voiceId: 'm1');
      final f = v.startListening();
      expect(v.open, isTrue);
      expect(v.phase, VoicePhase.starting);
      await f;
      expect(v.phase, VoicePhase.listening);
      expect(v.progress, '듣고 있어요');
      expect(v.voiceId, 'm1');
      expect(v.micActive, isTrue);
      v.apply(rec('m1', VoiceStatus.recognizing, text: '주방 불'));
      expect(v.phase, VoicePhase.recognizing);
      expect(v.progress, '알아듣는 중…');
      expect(v.heard, '주방 불');
      v.apply(rec('m1', VoiceStatus.received, text: '주방 불 켜줘'));
      expect(v.phase, VoicePhase.processing);
      expect(v.heard, '주방 불 켜줘');
      v.apply(rec('m1', VoiceStatus.executed, answer: '주방 조명을 켤게요.'));
      expect(v.phase, VoicePhase.completed);
      await tester.pump(const Duration(seconds: 4));
      expect(v.open, isFalse);
      expect(confirmer.cancels, isEmpty);
    });

    testWidgets('엔드포인트가 없으면(404) 잠깐 "쓸 수 없어요" 뒤 닫힘, 다시 시도하지 않음', (tester) async {
      confirmer.listenResult = null;
      await v.startListening();
      expect(v.phase, VoicePhase.error);
      expect(v.errorText, voiceUnavailable);
      await tester.pump(const Duration(seconds: 4));
      expect(v.open, isFalse);
      expect(confirmer.listens, 1);
    });

    testWidgets('409 = 이미 듣는 중 → 패널만 연다', (tester) async {
      confirmer.listenResult = () => const ListenStart(voiceId: 'other', alreadyListening: true);
      await v.startListening();
      expect(v.open, isTrue);
      expect(v.phase, VoicePhase.listening);
      expect(v.voiceId, 'other');
      v.close();
      await tester.pump();
      expect(confirmer.cancels, ['other']); // 닫으면 취소 (오류는 무시)
    });

    testWidgets('듣는 중에 닫으면 listen/cancel, 응답 전에 닫아도 취소', (tester) async {
      confirmer.listenResult = () => const ListenStart(voiceId: 'c1');
      await v.startListening();
      await v.toggleListen(); // 듣는 중에 다시 누르면 멈춤
      await tester.pump();
      expect(v.open, isFalse);
      expect(confirmer.cancels, ['c1']);

      final gate = Completer<ListenStart>();
      confirmer.listenResult = () => gate.future;
      final f = v.startListening();
      v.close();
      gate.complete(const ListenStart(voiceId: 'c2'));
      await f;
      await tester.pump();
      expect(v.open, isFalse);
      expect(confirmer.cancels, ['c1', 'c2']);
      // 닫은 명령의 늦은 상태는 다시 열지 않는다
      v.apply(rec('c1', VoiceStatus.recognizing));
      expect(v.open, isFalse);
    });

    testWidgets('WS listening 이 HTTP 응답보다 먼저 와도 그대로', (tester) async {
      final gate = Completer<ListenStart>();
      confirmer.listenResult = () => gate.future;
      final f = v.startListening();
      v.apply(rec('w1', VoiceStatus.listening, source: 'button'));
      v.apply(rec('w1', VoiceStatus.recognizing, text: '날씨'));
      gate.complete(const ListenStart(voiceId: 'w1'));
      await f;
      expect(v.phase, VoicePhase.recognizing);
      expect(v.heard, '날씨');
      v.close();
      await tester.pump();
    });

    testWidgets('호출어(source: wakeword)로 시작한 명령은 저절로 열림', (tester) async {
      v.apply(rec('h1', VoiceStatus.listening, source: 'wakeword'));
      expect(v.open, isTrue);
      expect(v.source, 'wakeword');
      expect(v.phase, VoicePhase.listening);
      // 아무 소식이 없으면 20초 뒤 닫힌다
      await tester.pump(const Duration(seconds: 21));
      expect(v.phase, VoicePhase.error);
      await tester.pump(const Duration(seconds: 4));
      expect(v.open, isFalse);
    });

    testWidgets('failed reason → 문구', (tester) async {
      v.apply(rec('f1', VoiceStatus.failed, reason: 'mic_unavailable'));
      expect(v.errorText, '마이크를 찾을 수 없어요');
      v.apply(rec('f2', VoiceStatus.failed, reason: 'no_speech'));
      expect(v.errorText, '말씀이 들리지 않았어요');
      v.apply(rec('f3', VoiceStatus.failed, reason: 'whatever'));
      expect(v.errorText, voiceUnavailable);
      await tester.pump(const Duration(seconds: 4));
    });
  });

  testWidgets('확인 409(다른 화면이 이미 답함) → 오류 없이 조용히 닫힘', (tester) async {
    confirmer.confirmError = const ApiError('지금 상태에서는 할 수 없는 동작이에요.', 409);
    v.apply(rec('r1', VoiceStatus.confirmRequired, confirmText: '주방 조명을 켤까요?'));
    v.approve();
    await tester.pump();
    expect(v.open, isFalse);
    expect(v.phase, VoicePhase.idle);
    expect(confirmer.calls, [('r1', true)]); // 닫을 때 confirm(false) 를 또 보내지 않는다
    // 다른 화면이 실행한 결과가 늦게 와도 다시 열지 않는다
    v.apply(rec('r1', VoiceStatus.executed, answer: '켰어요'));
    expect(v.open, isFalse);
  });

  testWidgets('확인 실패(409 아님) → "쓸 수 없어요"', (tester) async {
    confirmer.confirmError = const ApiError('서버 오류', 503);
    v.apply(rec('r2', VoiceStatus.confirmRequired, confirmText: '켤까요?'));
    v.approve();
    await tester.pump();
    expect(v.phase, VoicePhase.error);
    expect(v.errorText, voiceUnavailable);
    await tester.pump(const Duration(seconds: 4));
  });

  group('음성 설정 (호출어)', () {
    testWidgets('없는 백엔드 → 지원 안 함, 켜기 거부', (tester) async {
      await v.loadSettings();
      expect(v.settingsSupported, isFalse);
      expect(await v.setWakeWord(true), isFalse);
      expect(confirmer.saved, isEmpty);
    });

    testWidgets('읽기 · 켜기 (WS voice.settings 는 v7_test)', (tester) async {
      confirmer.settingsMissing = false;
      confirmer.settings = const VoiceSettings(wakeWord: false, standby: false);
      await v.loadSettings();
      expect(v.settingsSupported, isTrue);
      expect(v.wakeWord, isFalse);
      expect(await v.setWakeWord(true), isTrue);
      expect(v.wakeWord, isTrue);
      expect(v.standby, isTrue);
      expect(confirmer.saved, [true]);
    });
  });
}
