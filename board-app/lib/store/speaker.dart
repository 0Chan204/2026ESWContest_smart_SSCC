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
