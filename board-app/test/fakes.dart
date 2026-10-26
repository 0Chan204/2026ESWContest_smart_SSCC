import 'dart:async';
import 'dart:convert';

import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:web_socket_channel/web_socket_channel.dart';

import 'fixtures.dart';

/// 테스트용 WebSocket (서버 쪽에서 메시지를 밀어 넣는다)
class FakeChannel implements WebSocketChannel {
  FakeChannel(this.uri);
  final Uri uri;
  final controller = StreamController<dynamic>();
  @override
  late final WebSocketSink sink = FakeSink(this);
  @override
  Stream<dynamic> get stream => controller.stream;
  @override
  Future<void> get ready => Future.value();

  void push(String event, Map<String, dynamic> data, {String at = '2026-10-26T10:00:00Z'}) =>
      controller.add(jsonEncode({'event': event, 'at': at, 'data': data}));

  @override
  dynamic noSuchMethod(Invocation invocation) => super.noSuchMethod(invocation);
}

class FakeSink implements WebSocketSink {
  FakeSink(this.channel);
  final FakeChannel channel;
  @override
  Future close([int? closeCode, String? closeReason]) => channel.controller.close();
  @override
  dynamic noSuchMethod(Invocation invocation) => super.noSuchMethod(invocation);
}

/// 백엔드 흉내 (경로별 JSON). posts 에 보낸 요청이 쌓인다
class FakeBackend {
  FakeBackend({this.stoveOn = true, this.failSnapshot = false});
  bool stoveOn;
  bool failSnapshot;
  final posts = <(String, Object?)>[];
  final channels = <FakeChannel>[];
  int _cmd = 0;

  WebSocketChannel channel(Uri uri) {
    final ch = FakeChannel(uri);
    channels.add(ch);
    return ch;
  }

  late final http.Client client = MockClient((req) async {
    final path = req.url.path.replaceFirst('/api/v1', '');
    http.Response json(Object? body, [int status = 200]) =>
        http.Response.bytes(utf8.encode(jsonEncode(body)), status, headers: {'content-type': 'application/json; charset=utf-8'});
    if (req.method == 'POST') {
      final body = req.body.isEmpty ? null : jsonDecode(req.body);
      posts.add((path, body));
      if (path.endsWith('/commands') && path.startsWith('/devices/')) {
        return json({'commandId': 'cmd-${++_cmd}', 'deviceId': 'x', 'status': 'pending', 'issuedAt': 'now'}, 202);
      }
      if (path.endsWith('/feedback')) return json({'submittedAt': '2026-10-26T10:00:00Z'});
      if (path == '/voice/commands') return json({'voiceId': 'voice-1', 'status': 'received'}, 202);
      return json({'ok': true});
    }
    switch (path) {
      case '/snapshot':
        if (failSnapshot) return json({'detail': 'down'}, 503);
        return json(snapshotJson(stoveOn: stoveOn));
      case '/safety-events':
        return json({
          'items': [
            eventJson('e-old', 'auto_power_reduced', at: '2026-10-26T08:00:00Z', sessionId: 'sess-0'),
            eventJson('e-fall', 'fall_detected', room: 'toilet', at: '2026-10-26T09:00:00Z', severity: 'danger'),
            eventJson('e-new', 'auto_power_off', at: '2026-10-26T09:30:00Z', severity: 'danger'),
          ],
        });
      case '/user':
        return json({'detail': 'not found'}, 404);
      case '/guardian':
        return json({'name': '김보호', 'phone': '01012345678'});
      case '/policies/kitchen-absence':
        return json({'overheatEnterC': 150, 'reduceAfterSec': 180, 'offAfterSec': 600});
      case '/policies/fall-safety':
        return json({'autoReportSec': 60, 'userAlertWaitSec': 30});
      case '/sensing/results':
        return json({
          'items': [
            {'observedAt': DateTime.now().toUtc().toIso8601String(), 'room': 'kitchen', 'present': true, 'confidence': 0.87, 'activity': 'standing', 'validSec': 5},
          ],
        });
      case '/sensing/combined':
        return json({'locations': {'kitchen': {'node': {'node': 'r2', 'status': 'ok', 'quality': {'rssi': -50, 'rate_hz': 10}}}}});
      case '/sessions/sess-0':
        return json({'sessionId': 'sess-0', 'startedAt': '2026-10-26T07:50:00Z', 'endedAt': '2026-10-26T08:10:00Z', 'status': 'ended', 'peakTemperature': 140, 'timeline': []});
      case '/devices':
        return json({'items': []});
      case '/weather':
        return json({
          'available': true,
          'text': '오늘은 맑아요',
          'weather': {
            'location': '서울',
            'temperature': 18,
            'condition': '맑음',
            'weatherCode': 0,
            'tempMax': 21,
            'tempMin': 9,
            'hourly': [
              for (var h = 0; h < 12; h++)
                {'time': DateTime.now().add(Duration(hours: h)).toUtc().toIso8601String(), 'temperature': 18 + h % 3, 'weatherCode': h > 6 ? 61 : 0, 'precipitationProbability': h > 6 ? 60 : 0},
            ],
          },
        });
      default:
        return json({'detail': 'not found'}, 404);
    }
  });
}

/// 연결이 거부되는 클라이언트
class FakeDownClient extends http.BaseClient {
  @override
  Future<http.StreamedResponse> send(http.BaseRequest request) => Future.error(const SocketLikeError());
}

class SocketLikeError implements Exception {
  const SocketLikeError();
}
