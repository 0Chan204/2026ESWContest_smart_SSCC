// 음성 명령 창구 — 경로를 한곳에 모았다 (백엔드가 이름을 바꾸면 VoicePaths 만 고치면 된다).
//
// 지금 백엔드(v0.8)에 있는 것
//   POST /voice/commands                 { text, lang, source } → 202 { voiceId }
//   POST /voice/commands/{id}/confirm    { approved }  (이미 끝난 명령 409)
//
// 보드 마이크용 제안 계약 (백엔드가 녹음 + 음성 인식을 맡는다. 아직 없음 — README "음성 API 계약")
//   POST /voice/listen                   {} → 202 { voiceId }   (이미 듣는 중 409)
//   POST /voice/listen/cancel            { voiceId }            (오류는 무시)
//   GET  /voice/settings                 → { wakeWord, standby }
//   PUT  /voice/settings                 { wakeWord } → { wakeWord, standby }
//   WS   voice.status   status: listening · recognizing · (기존) received … failed, text, source, reason
//   WS   voice.settings { wakeWord, standby }
// 없는 경로(404 · 405)는 "아직 지원 안 함" 으로 보고 조용히 넘어간다 (다시 시도하지 않음).

import '../models/types.dart';
import 'home_source.dart';
import 'parse.dart';

typedef Requester = Future<Object?> Function(String method, String path, [Object? body]);

abstract final class VoicePaths {
  static const commands = '/voice/commands';
  static String confirm(String voiceId) => '/voice/commands/${Uri.encodeComponent(voiceId)}/confirm';
  static const listen = '/voice/listen';
  static const listenCancel = '/voice/listen/cancel';
  static const settings = '/voice/settings';
}

/// 듣기 시작 결과. alreadyListening = 409 (다른 곳에서 이미 듣는 중 — 패널만 연다)
class ListenStart {
  const ListenStart({this.voiceId, this.alreadyListening = false});
  final String? voiceId;
  final bool alreadyListening;
}

/// 음성 패널이 쓰는 창구 (테스트에서 바꿔 끼운다)
abstract class VoiceApi {
  Future<void> confirm(String voiceId, bool approved);

  /// 실패하면 ApiError (404 · 405 = 아직 없는 기능)
  Future<ListenStart> listen();
  Future<void> cancelListen(String voiceId);

  /// null = 이 백엔드에는 음성 설정이 없다 (404 · 405)
  Future<VoiceSettings?> loadSettings();
  Future<VoiceSettings> saveSettings({required bool wakeWord});
}

/// 없는 기능으로 볼 응답
bool isMissingEndpoint(Object e) => e is ApiError && (e.status == 404 || e.status == 405 || e.status == 501);

class VoiceService implements VoiceApi {
  VoiceService(this._request);
  final Requester _request;

  /// 인식이 끝난 전체 문장을 보낸다 (다른 입력 장치용 — 보드 화면은 쓰지 않는다)
  Future<String> send(String text, {double? confidence, String? recognizedAt}) async {
    final t = text.trim();
    final body = <String, Object?>{
      'text': t.length > 500 ? t.substring(0, 500) : t,
      'lang': 'ko-KR',
      'source': 'voice',
      if (recognizedAt != null) 'recognizedAt': recognizedAt,
      if (confidence != null && confidence >= 0 && confidence <= 1) 'confidence': confidence,
    };
    final r = obj(await _request('POST', VoicePaths.commands, body));
    final id = r?['voiceId'];
    if (id is! String || id.isEmpty) throw const ApiError('음성 명령 응답 형식이 올바르지 않아요.');
    return id;
  }

  @override
  Future<void> confirm(String voiceId, bool approved) async {
    await _request('POST', VoicePaths.confirm(voiceId), {'approved': approved});
  }

  @override
  Future<ListenStart> listen() async {
    try {
      final r = obj(await _request('POST', VoicePaths.listen, const <String, Object?>{}));
      return ListenStart(voiceId: _id(r));
    } on ApiError catch (e) {
      if (e.status == 409) {
        final b = obj(e.body);
        return ListenStart(voiceId: _id(b) ?? _id(obj(b?['detail'])), alreadyListening: true);
      }
      rethrow;
    }
  }

  @override
  Future<void> cancelListen(String voiceId) async {
    await _request('POST', VoicePaths.listenCancel, {'voiceId': voiceId});
  }

  @override
  Future<VoiceSettings?> loadSettings() async {
    try {
      return mapVoiceSettings(await _request('GET', VoicePaths.settings));
    } catch (e) {
      if (isMissingEndpoint(e)) return null;
      rethrow;
    }
  }

  @override
  Future<VoiceSettings> saveSettings({required bool wakeWord}) async {
    final r = await _request('PUT', VoicePaths.settings, {'wakeWord': wakeWord});
    // 응답 형식이 다르면 보낸 값으로 본다 (대기 표시는 켜진 쪽으로 — 마이크가 켜졌을 수 있음을 숨기지 않는다)
    return mapVoiceSettings(r) ?? VoiceSettings(wakeWord: wakeWord, standby: wakeWord);
  }

  static String? _id(Map<String, dynamic>? m) {
    final id = m?['voiceId'];
    return id is String && id.isNotEmpty && id.length <= 128 ? id : null;
  }
}
