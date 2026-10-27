// 음성 안내(TTS) 연결 지점. 보드에는 아직 음성 엔진이 없어 기본은 아무것도 하지 않는다.
// 보드 TTS 방식이 정해지면 Speaker 를 구현해 main.dart 에서 바꿔 끼우면 된다
// (안내 문장 · 낙상 경보 · 음성 명령 답변이 모두 이 한 곳을 지난다).

abstract class Speaker {
  void speak(String? text);
}

class SilentSpeaker implements Speaker {
  const SilentSpeaker();
  @override
  void speak(String? text) {}
}

/// 설정의 '위험 알림 음성 안내' 가 꺼져 있으면 읽지 않는다 (모든 안내가 이 한 곳을 지난다)
class GatedSpeaker implements Speaker {
  const GatedSpeaker(this.inner, this.enabled);
  final Speaker inner;
  final bool Function() enabled;
  @override
  void speak(String? text) {
    if (enabled()) inner.speak(text);
  }
}
