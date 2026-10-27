// 음성 명령 진행 상황 + 보드 마이크 (React useVoice 의 백엔드 경로).
// 녹음 · 음성 인식은 백엔드(보드 음성 서비스)가 한다 — 화면은 시작/취소만 보내고 WS voice.status 를 보여준다.
// 경로 · 형식은 data/voice_api.dart (보드 마이크 부분은 제안 계약, README 참고).
//
//   마이크 버튼      → POST /voice/listen → 202 { voiceId } (409 = 이미 듣는 중 → 패널만)
//                     없는 기능(404 · 405) · 실패 → "지금은 음성 명령을 쓸 수 없어요" 잠깐
//   listening        → "듣고 있어요" + 움직이는 막대
//   recognizing      → "알아듣는 중…" + 들린 글자(text)
//   received · thinking   → 진행 글자
//   confirm_required → confirmText + 남은 시간 → POST /voice/commands/{id}/confirm (409 = 다른 화면이 이미 답함 → 조용히 닫기)
//   executed · answered   → answer
//   cancelled · timeout   → "잘 듣지 못했어요"
//   failed           → reason 에 따라 (마이크 없음 · 말소리 없음) 아니면 "지금은 음성 명령을 쓸 수 없어요"
// 듣는 중에 패널을 닫으면 POST /voice/listen/cancel (오류 무시). 끝나면 잠시 뒤 저절로 닫힌다.
// 호출어(source: wakeword)로 시작한 명령도 voice.status 가 오면 패널이 저절로 열린다.

import 'dart:async';
import 'dart:math' as math;

import 'package:flutter/foundation.dart';

import '../../data/home_source.dart';
import '../../data/stream_message.dart';
import '../../models/types.dart';
import '../../store/home_store.dart';
import '../../store/speaker.dart';

enum VoicePhase { idle, starting, listening, recognizing, processing, confirm, completed, error }

const voiceUnavailable = '지금은 음성 명령을 쓸 수 없어요';
const voiceMisheard = '잘 듣지 못했어요';
const voiceNoMic = '마이크를 찾을 수 없어요';
const voiceNoSpeech = '말씀이 들리지 않았어요';
const voiceSttError = '잘 알아듣지 못했어요. 다시 말씀해 주세요';
const voiceInterrupted = '잠시 후 다시 말씀해 주세요';
const voiceHide = Duration(milliseconds: 3200);

/// 진행 중 단계에서 서버 응답이 끝내 오지 않을 때
const voiceSafety = Duration(seconds: 20);

/// failed 의 reason → 화면 문장
String voiceFailedText(String? reason) => switch (reason) {
      'mic_unavailable' => voiceNoMic,
      'no_speech' => voiceNoSpeech,
      'stt_error' => voiceSttError,
      'interrupted' => voiceInterrupted,
      // publish_failed(판정 엔진에 전달 실패) 와 모르는 이유
      _ => voiceUnavailable,
    };

class VoiceController extends ChangeNotifier {
  VoiceController({required HomeStore store, required Speaker speaker, VoiceApi? api})
      : _speaker = speaker,
        _api = api ?? store.source.voice {
    _unsubscribe = store.subscribeStream(_onMessage);
  }

  /// 스토어 없이 (테스트)
  VoiceController.detached({required Speaker speaker, required VoiceApi api})
      : _speaker = speaker,
        _api = api;

  final Speaker _speaker;
  final VoiceApi _api;
  void Function()? _unsubscribe;
  final List<Timer> _timers = [];
  bool _disposed = false;

  bool open = false;
  VoicePhase phase = VoicePhase.idle;

  /// 지금 보여주는 음성 명령
  String? voiceId;

  /// 사용자가 닫은 명령 (늦게 온 상태가 패널을 다시 열지 않게, 최근 것만)
  final List<String> _closed = [];

  /// 인식한 문장 (서버가 시작어를 뗀 것)
  String heard = '';
  String progress = '';
  String reply = '';
  String errorText = voiceMisheard;
  String? confirmText;
  String? confirmDeadline;

  /// 이 명령을 시작한 곳 (button · wakeword …)
  String? source;
  bool _confirming = false;

  // 마이크 버튼 → 듣기 시작 요청
  bool _starting = false;
  bool _cancelWhenStarted = false;
  int _listenSeq = 0;

  // ── 보드 음성 설정 (GET · PUT /voice/settings, WS voice.settings) ─────────
  /// null = 아직 모름, false = 이 백엔드에는 없음, true = 있음
  bool? settingsSupported;
  bool wakeWord = false;

  /// 호출어를 기다리며 마이크가 켜져 있음 (레일에 '호출어 대기' 표시)
  bool standby = false;

  /// 보드 스피커 안내 (서버 값). null = 서버가 알려 주지 않음 → 화면 설정만 쓴다
  bool? speak;
  bool settingsBusy = false;
  bool _settingsLoading = false;

  bool get micActive => open && (phase == VoicePhase.starting || phase == VoicePhase.listening || phase == VoicePhase.recognizing);

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
    if (m is VoiceSettingsMsg) _applySettings(m.settings);
  }

  void _applySettings(VoiceSettings s) {
    if (_disposed) return;
    settingsSupported = true;
    wakeWord = s.wakeWord;
    standby = s.standby;
    speak = s.speak ?? speak;
    _notify();
  }

  void _reset(String? id) {
    _clearTimers();
    voiceId = id;
    heard = '';
    reply = '';
    progress = '';
    source = null;
    confirmText = null;
    confirmDeadline = null;
    _confirming = false;
  }

  /// voice.status 하나 반영
  void apply(VoiceRecord rec) {
    if (_disposed || _closed.contains(rec.voiceId)) return;
    if (rec.voiceId != voiceId) {
      // 새 명령이 오면 그 명령으로 바꿔 보여준다 (앞 명령의 확인 창은 서버가 마감 뒤 취소)
      _reset(rec.voiceId);
      open = true;
    }
    open = true;
    if (rec.source != null) source = rec.source;
    if (rec.text != null) heard = rec.text!;
    switch (rec.status) {
      case VoiceStatus.listening:
        _listening();
      case VoiceStatus.recognizing:
        _step(VoicePhase.recognizing, '알아듣는 중…');
      case VoiceStatus.received:
        _step(VoicePhase.processing, '알아들었어요');
      case VoiceStatus.thinking:
        _step(VoicePhase.processing, '확인하고 있어요');
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
          if (voiceId == id && phase == VoicePhase.confirm) {
            _fail(voiceMisheard);
            _notify();
          }
        });
      case VoiceStatus.executed:
        _finish(rec.answer ?? '실행했어요.');
      case VoiceStatus.answered:
        _finish(rec.answer ?? '알겠어요.');
      case VoiceStatus.cancelled:
      case VoiceStatus.timeout:
        _fail(voiceMisheard);
      case VoiceStatus.failed:
        _fail(voiceFailedText(rec.reason));
    }
    _notify();
  }

  void _listening() => _step(VoicePhase.listening, '듣고 있어요');

  /// 진행 중 단계. 서버 소식이 끝내 없으면 닫는다
  void _step(VoicePhase p, String text) {
    phase = p;
    progress = text;
    _clearTimers();
    final id = voiceId;
    _later(voiceSafety, () {
      if (voiceId == id && phase == p) {
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

  // ── 마이크 버튼 ──────────────────────────────────────────────────────────
  /// 듣는 중이면 멈추고, 아니면 듣기 시작
  Future<void> toggleListen() async {
    if (micActive) {
      close();
      return;
    }
    await startListening();
  }

  /// POST /voice/listen. 실패 · 없는 기능이면 잠깐 "쓸 수 없어요" (다시 시도하지 않는다)
  Future<void> startListening() async {
    if (_disposed || _starting) return;
    final seq = ++_listenSeq;
    _reset(null);
    _starting = true;
    _cancelWhenStarted = false;
    open = true;
    phase = VoicePhase.starting;
    progress = '마이크를 켜고 있어요';
    _notify();
    try {
      final r = await _api.listen();
      if (_disposed) return;
      final id = r.voiceId;
      if (_cancelWhenStarted || seq != _listenSeq) {
        // 응답 전에 닫았다 → 이 화면이 시작한 것만 취소
        if (id != null && !r.alreadyListening) _cancelQuietly(id);
        return;
      }
      if (phase == VoicePhase.starting) {
        voiceId = id;
        _listening();
        // 이미 다른 곳에서 듣던 명령이면 그 명령의 지금 단계(듣는 중 · 알아듣는 중 · 확인 …)로 맞춘다
        if (r.alreadyListening && id != null) {
          final rec = await _api.getCommand(id);
          if (!_disposed && rec != null && voiceId == id && seq == _listenSeq) apply(rec);
        }
      } else {
        // WS voice.status 가 먼저 와서 이미 바뀌었다
        voiceId ??= id;
      }
    } catch (_) {
      if (_disposed || _cancelWhenStarted || seq != _listenSeq) return;
      if (phase == VoicePhase.starting) _fail(voiceUnavailable);
    } finally {
      if (seq == _listenSeq) _starting = false;
      _notify();
    }
  }

  void _cancelQuietly(String id) {
    _api.cancelListen(id).catchError((Object _) {/* 무시: 서버가 시간이 지나면 끝낸다 */});
  }

  /// 실행 (확인 창)
  void approve() {
    final id = voiceId;
    if (id == null || !_confirming) return;
    _confirming = false;
    confirmText = null;
    _step(VoicePhase.processing, '실행하고 있어요');
    _api.confirm(id, true).catchError((Object e) {
      if (voiceId != id) return;
      if (e is ApiError && e.status == 409) {
        // 다른 화면이 이미 답했다 → 오류 없이 닫는다
        close();
      } else {
        _fail(voiceUnavailable);
        _notify();
      }
    });
    _notify();
  }

  /// 취소 (확인 창) = 닫기
  void cancel() => close();

  /// 닫기. 확인 창이면 취소를, 듣는 중이면 듣기 취소를 보낸다
  void close() {
    _clearTimers();
    final id = voiceId;
    if (id != null && _confirming) {
      _api.confirm(id, false).catchError((Object _) {/* 서버가 마감 뒤 자동 취소 · 409 = 이미 답함 */});
    }
    if (_starting) _cancelWhenStarted = true;
    if (id != null && (phase == VoicePhase.listening || phase == VoicePhase.recognizing)) _cancelQuietly(id);
    if (id != null) {
      _closed.add(id);
      if (_closed.length > 20) _closed.removeAt(0);
    }
    _confirming = false;
    open = false;
    phase = VoicePhase.idle;
    heard = '';
    reply = '';
    progress = '';
    source = null;
    confirmText = null;
    confirmDeadline = null;
    _notify();
  }

  // ── 음성 설정 ────────────────────────────────────────────────────────────
  /// 앱 시작 · 설정 화면을 열 때. 없는 기능이면 settingsSupported = false (다시 묻지 않는 건 화면 쪽 몫)
  Future<void> loadSettings() async {
    if (_disposed || _settingsLoading) return;
    _settingsLoading = true;
    try {
      final s = await _api.loadSettings();
      if (_disposed) return;
      if (s == null) {
        settingsSupported = false;
        wakeWord = false;
        standby = false;
      } else {
        settingsSupported = true;
        wakeWord = s.wakeWord;
        standby = s.standby;
        speak = s.speak ?? speak;
      }
    } catch (_) {
      // 연결 문제: 지난 값 그대로
    } finally {
      _settingsLoading = false;
      _notify();
    }
  }

  /// 호출어 켜기 · 끄기. 실패하면 되돌리고 false
  Future<bool> setWakeWord(bool on) async {
    if (_disposed || settingsSupported != true || settingsBusy) return false;
    final before = (wakeWord, standby);
    wakeWord = on;
    settingsBusy = true;
    _notify();
    try {
      final s = await _api.saveSettings(wakeWord: on);
      wakeWord = s.wakeWord;
      standby = s.standby;
      speak = s.speak ?? speak;
      return true;
    } catch (e) {
      wakeWord = before.$1;
      standby = before.$2;
      if (isMissingEndpoint(e)) settingsSupported = false;
      return false;
    } finally {
      settingsBusy = false;
      _notify();
    }
  }

  /// 보드 스피커 안내 켜기 · 끄기 (설정 '위험 알림 음성 안내'). 서버에 설정이 없으면 true(화면 설정만 바꾼 것으로 본다)
  Future<bool> setSpeak(bool on) async {
    if (_disposed || settingsSupported != true) return true;
    final before = speak;
    speak = on;
    _notify();
    try {
      final s = await _api.saveSettings(speak: on);
      speak = s.speak ?? on;
      wakeWord = s.wakeWord;
      standby = s.standby;
      return true;
    } catch (e) {
      speak = before;
      if (isMissingEndpoint(e)) {
        settingsSupported = false;
        return true;
      }
      return false;
    } finally {
      _notify();
    }
  }

  @override
  void dispose() {
    _disposed = true;
    _clearTimers();
    _unsubscribe?.call();
    super.dispose();
  }
}
