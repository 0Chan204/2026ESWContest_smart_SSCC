// 음성 명령 진행 상황 (React useVoice 의 백엔드 경로만). 보드에는 아직 음성 인식(STT)이 없어
// 화면이 명령을 보내지 않는다 — 다른 입력 장치가 POST /voice/commands 로 보낸 명령의
// WS voice.status 를 받아 패널에 보여주고, 확인이 필요하면 여기서 실행/취소를 보낸다.
//
//   received · thinking   → 진행 글자
//   confirm_required      → confirmText + confirmDeadline 까지 남은 시간 → POST /voice/commands/{id}/confirm
//   executed · answered   → answer
//   cancelled · timeout   → "잘 듣지 못했어요"
//   failed                → "지금은 음성 명령을 쓸 수 없어요"
// 끝나면 잠시 뒤 저절로 닫힌다. 언제나 가장 최근 voiceId 하나만 보여준다.

import 'dart:async';
import 'dart:math' as math;

import 'package:flutter/foundation.dart';

import '../../data/home_source.dart';
import '../../data/stream_message.dart';
import '../../models/types.dart';
import '../../store/home_store.dart';
import '../../store/speaker.dart';

enum VoicePhase { idle, processing, confirm, completed, error }

const voiceUnavailable = '지금은 음성 명령을 쓸 수 없어요';
const voiceMisheard = '잘 듣지 못했어요';
const voiceHide = Duration(milliseconds: 3200);

/// 진행 중 단계에서 서버 응답이 끝내 오지 않을 때
const voiceSafety = Duration(seconds: 20);

/// 음성 명령 확인 · 취소 창구 (테스트에서 바꿔 끼운다)
abstract class VoiceConfirmer {
  Future<void> confirm(String voiceId, bool approved);
}

class _SourceConfirmer implements VoiceConfirmer {
  _SourceConfirmer(this.service);
  final VoiceService service;
  @override
  Future<void> confirm(String voiceId, bool approved) => service.confirm(voiceId, approved);
}

class VoiceController extends ChangeNotifier {
  VoiceController({required HomeStore store, required Speaker speaker, VoiceConfirmer? confirmer})
      : _speaker = speaker,
        _confirmer = confirmer ?? _SourceConfirmer(store.source.voice) {
    _unsubscribe = store.subscribeStream(_onMessage);
  }

  /// 스토어 없이 (테스트)
  VoiceController.detached({required Speaker speaker, required VoiceConfirmer confirmer})
      : _speaker = speaker,
        _confirmer = confirmer;

  final Speaker _speaker;
  final VoiceConfirmer _confirmer;
  void Function()? _unsubscribe;
  final List<Timer> _timers = [];
  bool _disposed = false;

  bool open = false;
  VoicePhase phase = VoicePhase.idle;

  /// 지금 보여주는 음성 명령
  String? voiceId;

  /// 인식한 문장 (서버가 시작어를 뗀 것)
  String heard = '';
  String progress = '';
  String reply = '';
  String errorText = voiceMisheard;
  String? confirmText;
  String? confirmDeadline;
  bool _confirming = false;

  void _later(Duration d, void Function() fn) => _timers.add(Timer(d, fn));

  void _clearTimers() {
    for (final t in _timers) {
      t.cancel();
    }
    _timers.clear();
  }

  void _notify() {
    if (!_disposed) notifyListeners();
  }

  void _onMessage(StreamMessage m) {
    if (m is VoiceMsg) apply(m.record);
  }

  /// voice.status 하나 반영
  void apply(VoiceRecord rec) {
    if (_disposed) return;
    // 사용자가 닫은 명령의 늦은 상태는 무시한다
    if (rec.voiceId == voiceId && !open) return;
    if (rec.voiceId != voiceId) {
      // 새 명령이 오면 그 명령으로 바꿔 보여준다 (앞 명령의 확인 창은 서버가 마감 뒤 취소)
      _clearTimers();
      voiceId = rec.voiceId;
      heard = '';
      reply = '';
      confirmText = null;
      confirmDeadline = null;
      _confirming = false;
      open = true;
    }
    if (rec.text != null) heard = rec.text!;
    switch (rec.status) {
      case VoiceStatus.received:
        _processing('알아들었어요');
      case VoiceStatus.thinking:
        _processing('확인하고 있어요');
      case VoiceStatus.confirmRequired:
        _clearTimers();
        _confirming = true;
        confirmText = rec.confirmText ?? '실행할까요?';
        confirmDeadline = rec.confirmDeadline;
        phase = VoicePhase.confirm;
        // 답이 없으면 서버가 취소한다 (마감 + 여유 5초 뒤에도 소식이 없으면 닫는다)
        final left = rec.confirmDeadline == null ? null : DateTime.tryParse(rec.confirmDeadline!)?.difference(DateTime.now());
        final wait = left == null ? const Duration(seconds: 35) : Duration(milliseconds: math.max(0, left.inMilliseconds) + 5000);
        final id = voiceId;
        _later(wait, () {
          if (voiceId == id && phase == VoicePhase.confirm) _fail(voiceMisheard);
        });
      case VoiceStatus.executed:
        _finish(rec.answer ?? '실행했어요.');
      case VoiceStatus.answered:
        _finish(rec.answer ?? '알겠어요.');
      case VoiceStatus.cancelled:
      case VoiceStatus.timeout:
        _fail(voiceMisheard);
      case VoiceStatus.failed:
        _fail(voiceUnavailable);
    }
    _notify();
  }

  void _processing(String text) {
    phase = VoicePhase.processing;
    progress = text;
    _clearTimers();
    final id = voiceId;
    _later(voiceSafety, () {
      if (voiceId == id && phase == VoicePhase.processing) {
        _fail(voiceMisheard);
        _notify();
      }
    });
  }

  void _finish(String text) {
    _clearTimers();
    _confirming = false;
    confirmText = null;
    reply = text;
    phase = VoicePhase.completed;
    _speaker.speak(text);
    final ms = math.max(voiceHide.inMilliseconds, text.length * 110);
    _later(Duration(milliseconds: ms), close);
  }

  void _fail(String text) {
    _clearTimers();
    _confirming = false;
    confirmText = null;
    errorText = text;
    phase = VoicePhase.error;
    _later(voiceHide, close);
  }

  /// 실행 (확인 창)
  void approve() {
    final id = voiceId;
    if (id == null || !_confirming) return;
    _confirming = false;
    confirmText = null;
    _processing('실행하고 있어요');
    _confirmer.confirm(id, true).catchError((Object _) {
      if (voiceId == id) {
        _fail(voiceUnavailable);
        _notify();
      }
    });
    _notify();
  }

  /// 취소 (확인 창) = 닫기
  void cancel() => close();

  /// 닫기. 확인 창이 떠 있는 채로 닫으면 실행하지 않도록 취소를 보낸다
  void close() {
    _clearTimers();
    final id = voiceId;
    if (id != null && _confirming) {
      _confirmer.confirm(id, false).catchError((Object _) {/* 서버가 마감 뒤 자동 취소 */});
    }
    _confirming = false;
    open = false;
    phase = VoicePhase.idle;
    heard = '';
    reply = '';
    progress = '';
    confirmText = null;
    confirmDeadline = null;
    // voiceId 는 남겨 둔다 — 닫은 명령의 늦은 상태가 패널을 다시 열지 않게
    _notify();
  }

  @override
  void dispose() {
    _disposed = true;
    _clearTimers();
    _unsubscribe?.call();
    super.dispose();
  }
}
