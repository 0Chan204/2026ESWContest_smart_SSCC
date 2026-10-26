// 실제 백엔드 연동 (HomeVIS-Backend v0.7.x). React httpSource.ts 와 같은 API · 같은 순서.
//
//   loadSnapshot     GET  /snapshot · /safety-events · /sessions/{id} · /user · /guardian
//                         · /policies/kitchen-absence · /policies/fall-safety · /sensing/results?limit=60
//   subscribe        WS   /stream  (끊기면 1초부터 10초까지 늘려 가며 다시 연결, ?since=마지막 안전 이벤트 id)
//                    GET  /devices  (15초마다 — 온라인 상태가 바뀐 기기만 알린다)
//   controlDevice    POST /devices/{id}/commands  (전등 on · off · fadeout, 환풍기 on · off · set_speed,
//                         공기청정기 on · off · set_mode. 인덕션 · 정수기는 조회 전용)
//   loadSensingNodes GET  /sensing/combined
//   loadWeather      GET  /weather
//   submitFeedback   POST /safety-events/{id}/feedback
//   voice            POST /voice/commands · /voice/commands/{voiceId}/confirm

import 'dart:async';
import 'dart:convert';

import 'package:http/http.dart' as http;
import 'package:web_socket_channel/web_socket_channel.dart';

import '../config.dart';
import '../models/types.dart';
import 'parse.dart';
import 'stream_message.dart';
import 'translator.dart';

const _devicePoll = Duration(seconds: 15);
const _requestTimeout = Duration(seconds: 10);
const _sessionFetchLimit = 10;

/// 노드 메시지가 이보다 오래되면 '응답 없음'
const nodeStaleSec = 10;

/// 화면에 그대로 보여줘도 되는 오류 문장 (서버 응답 본문은 노출하지 않는다)
class ApiError implements Exception {
  const ApiError(this.message, [this.status = 0]);
  final String message;
  final int status;
  @override
  String toString() => message;
}

String apiErrorMessage(int status) {
  if (status == 404) return '찾을 수 없어요.';
  if (status == 409) return '지금 상태에서는 할 수 없는 동작이에요.';
  if (status == 422) return '입력값을 확인해 주세요.';
  if (status >= 500) return '서버에서 오류가 났어요. 잠시 후 다시 시도해 주세요.';
  return '요청을 처리하지 못했어요.';
}

typedef StreamListener = void Function(StreamMessage message);
typedef ChannelFactory = WebSocketChannel Function(Uri uri);

class HomeSource {
  HomeSource({http.Client? client, String? apiBase, ChannelFactory? channelFactory})
      : _client = client ?? http.Client(),
        _root = apiRoot(apiBase ?? apiBaseRaw),
        _apiBase = apiBase ?? apiBaseRaw,
        _channelFactory = channelFactory ?? WebSocketChannel.connect;

  final http.Client _client;
  final String _root;
  final String _apiBase;
  final ChannelFactory _channelFactory;
  final BackendTranslator translator = BackendTranslator();

  // ── HTTP ────────────────────────────────────────────────────────────────
  Future<Object?> _request(String method, String path, [Object? body]) async {
    final uri = Uri.parse('$_root$path');
    http.Response res;
    try {
      final headers = <String, String>{'Accept': 'application/json'};
      if (body != null) headers['Content-Type'] = 'application/json';
      final req = method == 'GET'
          ? _client.get(uri, headers: headers)
          : method == 'PUT'
              ? _client.put(uri, headers: headers, body: jsonEncode(body))
              : _client.post(uri, headers: headers, body: jsonEncode(body));
      res = await req.timeout(_requestTimeout);
    } catch (_) {
      throw const ApiError('서버에 연결하지 못했어요. 백엔드가 실행 중인지 확인해 주세요.');
    }
    if (res.statusCode < 200 || res.statusCode >= 300) throw ApiError(apiErrorMessage(res.statusCode), res.statusCode);
    if (res.statusCode == 204 || res.bodyBytes.isEmpty) return null;
    try {
      return jsonDecode(utf8.decode(res.bodyBytes));
    } catch (_) {
      throw const ApiError('서버 응답 형식이 올바르지 않아요.');
    }
  }

  Future<Object?> _get(String path) => _request('GET', path);

  /// 404 면 null (아직 등록 · 수신된 값이 없는 경우)
  Future<Object?> _getOrNull(String path) async {
    try {
      return await _get(path);
    } on ApiError catch (e) {
      if (e.status == 404) return null;
      rethrow;
    }
  }

  Future<Object?> _quiet(String path) async {
    try {
      return await _get(path);
    } catch (_) {
      return null;
    }
  }

  Future<Snapshot> loadSnapshot() async {
    final results = await Future.wait([
      _get('/snapshot'),
      _get('/safety-events?page=1&size=200'),
      _getOrNull('/user'),
      _getOrNull('/guardian'),
      _get('/policies/kitchen-absence'),
      _get('/policies/fall-safety'),
      _quiet('/sensing/results?limit=$historyLen'),
    ]);
    final snap = obj(results[0]);
    if (snap == null) throw const ApiError('서버 응답 형식이 올바르지 않아요.');
    final devices = translator.buildDevices(snap);

    // 서버는 오래된 것부터 준다 → 화면은 최신이 앞
    final events = objs(obj(results[1])?['items']).map(mapEvent).whereType<SafetyEvent>().toList().reversed.toList();

    final session = mapSession(snap['session']);
    final ids = <String>[];
    for (final e in events) {
      final s = e.sessionId;
      if (s != null && s.isNotEmpty && s != session?.sessionId && !ids.contains(s)) ids.add(s);
      if (ids.length >= _sessionFetchLimit) break;
    }
    final fetched = await Future.wait(ids.map((id) => _quiet('/sessions/${Uri.encodeComponent(id)}')));
    final sessions = [if (session != null) session, ...fetched.map(mapSession).whereType<CookingSession>()];

    final rooms = obj(snap['rooms']) ?? const <String, dynamic>{};
    Presence? presenceOf(String key) => mapPresence(obj(rooms[key])?['presence']);
    final kitchen = presenceOf('kitchen') ?? unknownPresence(RoomId.kitchen);
    final bathroom = presenceOf('toilet') ?? presenceOf('bathroom') ?? unknownPresence(RoomId.bathroom);

    final sensing = objs(obj(results[6])?['items']).map(mapSensing).whereType<SensingSample>().toList();
    var location = sensing.isEmpty ? Location.unknown : (sensing.last.room?.location ?? Location.unknown);
    if (location == Location.unknown && kitchen.present) location = Location.kitchen;

    return Snapshot(
      devices: devices,
      kitchenPresence: kitchen,
      bathroomPresence: bathroom,
      location: location,
      sensing: sensing,
      session: session,
      sessions: sessions,
      events: events,
      // 진행 중인 낙상 사건 목록 API 가 없어 처음엔 비워 두고, WebSocket fall.incident 로 받는다
      fall: null,
      contacts: Contacts(user: mapContact(results[2]), guardian: mapContact(results[3])),
      policy: mapPolicy(results[4]),
      fallPolicy: mapFallPolicy(results[5]),
    );
  }

  // ── 실시간 ──────────────────────────────────────────────────────────────
  /// WebSocket 연결 + 기기 온라인 폴링. 해제 함수를 돌려준다.
  void Function() subscribe(StreamListener listener, {void Function(bool connected)? onConnection}) {
    WebSocketChannel? channel;
    StreamSubscription<dynamic>? sub;
    Timer? retryTimer;
    var closed = false;
    var retry = const Duration(seconds: 1);
    String? lastEventId;

    void handle(dynamic raw) {
      if (raw is! String || raw.length > 1000000) return;
      Object? env;
      try {
        env = jsonDecode(raw);
      } catch (_) {
        return;
      }
      final e = obj(env);
      final data = obj(e?['data']);
      final event = e?['event'];
      if (e == null || event is! String || data == null) return;
      if (event == 'safety.event' && data['eventId'] is String) lastEventId = data['eventId'] as String;
      List<StreamMessage> msgs;
      try {
        msgs = translator.translate(event, str(e['at'], nowIso()), data);
      } catch (_) {
        return; // 이상한 메시지 하나가 연결을 끊지 않게
      }
      for (final m in msgs) {
        listener(m);
      }
    }

    late void Function() connect;
    void scheduleRetry() {
      if (closed) return;
      onConnection?.call(false);
      retryTimer?.cancel();
      retryTimer = Timer(retry, connect);
      final next = retry * 2;
      retry = next > const Duration(seconds: 10) ? const Duration(seconds: 10) : next;
    }

    connect = () {
      if (closed) return;
      final WebSocketChannel ch;
      try {
        ch = _channelFactory(streamUri(since: lastEventId, raw: _apiBase));
      } catch (_) {
        scheduleRetry();
        return;
      }
      channel = ch;
      var done = false;
      void finish() {
        if (done) return;
        done = true;
        sub?.cancel();
        sub = null;
        if (identical(channel, ch)) channel = null;
        scheduleRetry();
      }

      ch.ready.then((_) {
        if (closed) return;
        retry = const Duration(seconds: 1);
        onConnection?.call(true);
      }).catchError((Object _) {
        finish();
      });
      sub = ch.stream.listen(handle, onDone: finish, onError: (Object _) => finish(), cancelOnError: true);
    };
    connect();

    final poll = Timer.periodic(_devicePoll, (_) async {
      try {
        final res = await _get('/devices');
        for (final m in translator.connectionChanges(res)) {
          listener(m);
        }
      } catch (_) {
        // 다음 주기에 다시
      }
    });

    return () {
      closed = true;
      retryTimer?.cancel();
      poll.cancel();
      sub?.cancel();
      channel?.sink.close();
    };
  }

  // ── 동작 ────────────────────────────────────────────────────────────────
  Future<void> _command(String deviceId, Map<String, Object?> body) async {
    final r = await _request('POST', '/devices/${Uri.encodeComponent(deviceId)}/commands', body);
    final id = obj(r)?['commandId'];
    if (id is String) translator.rememberCommand(id);
  }

  /// 전등 · 환풍기 · 공기청정기 제어. 실제 상태는 기기 응답(WS device.state)이 오면 바뀐다.
  /// - 전등 { brightness } → 가장 가까운 단계: 0 off · 20 fadeout · 100 on. 꺼진 전등은 on 다음 fadeout
  Future<void> controlDevice(String deviceId, DeviceControl control) async {
    Device? d;
    for (final x in translator.devices) {
      if (x.id == deviceId) d = x;
    }
    if (d == null) throw const ApiError('등록되지 않은 기기예요.');
    switch (d) {
      case LightDevice():
        final b = control.brightness;
        if (b != null) {
          final target = nearestLightStep(b);
          if (target == 0) return _command(deviceId, {'type': 'off'});
          if (target == 100) return _command(deviceId, {'type': 'on'});
          if (!d.on) await _command(deviceId, {'type': 'on'});
          return _command(deviceId, {'type': 'fadeout'});
        }
        if (control.on == null) throw const ApiError('전등은 켜기·끄기와 절전만 할 수 있어요.');
        return _command(deviceId, {'type': control.on! ? 'on' : 'off'});
      case FanDevice():
        if (control.speed != null) return _command(deviceId, {'type': 'set_speed', 'speed': speedToBackend(control.speed!)});
        if (control.on == null) throw const ApiError('환풍기는 켜기·끄기와 풍량만 바꿀 수 있어요.');
        return _command(deviceId, {'type': control.on! ? 'on' : 'off'});
      case AirPurifierDevice():
        if (control.mode != null) return _command(deviceId, {'type': 'set_mode', 'mode': control.mode!.name});
        if (control.on == null) throw const ApiError('공기청정기는 켜기·끄기와 운전 모드만 바꿀 수 있어요.');
        return _command(deviceId, {'type': control.on! ? 'on' : 'off'});
      case InductionDevice():
      case PurifierDevice():
        throw const ApiError('이 기기는 화면에서 제어할 수 없어요.');
    }
  }

  Future<List<SensingNode>> loadSensingNodes() async => parseSensingNodes(await _get('/sensing/combined'), DateTime.now());

  Future<Weather?> loadWeather() async => mapWeather(await _get('/weather'));

  Future<Feedback> submitFeedback(String eventId, Verdict verdict) async {
    final r = await _request('POST', '/safety-events/${Uri.encodeComponent(eventId)}/feedback', {'verdict': verdict.name});
    return Feedback(verdict: verdict, submittedAt: str(obj(r)?['submittedAt'], nowIso()));
  }

  late final VoiceService voice = VoiceService(this);
}

/// 백엔드 음성 명령 창구. 보드에는 아직 음성 인식(STT)이 없어 화면에서 send 를 쓰지 않는다.
/// 음성 인식이 정해지면 인식한 전체 문장을 send 로 보내면 된다 (진행 상황은 WS voice.status).
class VoiceService {
  VoiceService(this._source);
  final HomeSource _source;

  Future<String> send(String text, {double? confidence, String? recognizedAt}) async {
    final t = text.trim();
    final body = <String, Object?>{
      'text': t.length > 500 ? t.substring(0, 500) : t,
      'lang': 'ko-KR',
      'source': 'voice',
      if (recognizedAt != null) 'recognizedAt': recognizedAt,
      if (confidence != null && confidence >= 0 && confidence <= 1) 'confidence': confidence,
    };
    final r = obj(await _source._request('POST', '/voice/commands', body));
    final id = r?['voiceId'];
    if (id is! String || id.isEmpty) throw const ApiError('음성 명령 응답 형식이 올바르지 않아요.');
    return id;
  }

  Future<void> confirm(String voiceId, bool approved) async {
    await _source._request('POST', '/voice/commands/${Uri.encodeComponent(voiceId)}/confirm', {'approved': approved});
  }
}

/// GET /sensing/combined → 공간별 노드 상태 (서버는 노드 메시지를 해석하지 않으므로 여기서 본다)
List<SensingNode> parseSensingNodes(Object? raw, DateTime now) {
  final locations = obj(obj(raw)?['locations']) ?? const <String, dynamic>{};
  final nowSec = now.millisecondsSinceEpoch / 1000;
  const plan = [
    ('kitchen', HouseRoom.kitchen, 'r2'),
    ('room', HouseRoom.bedroom, 'r1'),
    ('toilet', HouseRoom.bathroom, 'r3'),
  ];
  final idPattern = RegExp(r'^[\w-]{1,16}$');
  return [
    for (final (key, room, fallbackId) in plan)
      () {
        final node = obj(obj(locations[key])?['node']);
        if (node == null) return SensingNode(room: room, node: fallbackId, status: NodeStatus.missing);
        final q = obj(node['quality']) ?? const <String, dynamic>{};
        final tEnd = optNum(node['t_end']);
        final stale = tEnd != null && nowSec - tEnd > nodeStaleSec;
        final rawStatus = str(node['status']);
        final status = (stale || rawStatus == 'stopped')
            ? NodeStatus.stale
            : rawStatus == 'ok'
                ? NodeStatus.ok
                : NodeStatus.other;
        final id = str(node['node'], fallbackId);
        return SensingNode(
          room: room,
          node: idPattern.hasMatch(id) ? id : fallbackId,
          status: status,
          rssi: status == NodeStatus.ok ? optNum(q['rssi']) : null,
          rateHz: status == NodeStatus.ok ? optNum(q['rate_hz']) : null,
        );
      }(),
  ];
}
