import 'package:flutter_test/flutter_test.dart';
import 'package:homevis_gui/features/voice/voice_controller.dart';
import 'package:homevis_gui/models/types.dart';
import 'package:homevis_gui/store/speaker.dart';

class FakeConfirmer implements VoiceConfirmer {
  final calls = <(String, bool)>[];
  @override
  Future<void> confirm(String voiceId, bool approved) async => calls.add((voiceId, approved));
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
    v = VoiceController.detached(speaker: speaker, confirmer: confirmer);
  });
  tearDown(() => v.dispose());

  VoiceRecord rec(String id, VoiceStatus s, {String? text, String? answer, String? confirmText, String? deadline}) =>
      VoiceRecord(voiceId: id, status: s, text: text, answer: answer, confirmText: confirmText, confirmDeadline: deadline);

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
}
