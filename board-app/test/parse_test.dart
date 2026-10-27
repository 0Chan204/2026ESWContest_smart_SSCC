import 'package:flutter_test/flutter_test.dart';
import 'package:homevis_gui/data/parse.dart';
import 'package:homevis_gui/models/types.dart';

void main() {
  group('작은 검사 도구', () {
    test('obj · num · str 는 이상한 값에서 기본값', () {
      expect(obj(null), isNull);
      expect(obj([1]), isNull);
      expect(obj({1: 'a'})?['1'], 'a');
      expect(numOr('3'), 0);
      expect(numOr(double.nan, 7), 7);
      expect(optNum(double.infinity), isNull);
      expect(str(5, 'x'), 'x');
      expect(objs([1, {'a': 1}, null]).length, 1);
    });
  });

  group('공간 · 위치', () {
    test('백엔드 구역 이름', () {
      expect(mapRoom('toilet'), RoomId.bathroom);
      expect(mapRoom('room'), RoomId.bedroom);
      expect(mapRoom('kitchen'), RoomId.kitchen);
      expect(mapRoom('living'), RoomId.home);
      expect(mapRoom(null), RoomId.home);
      expect(mapLocation('outside'), Location.outside);
      expect(mapLocation('living'), Location.unknown);
    });
  });

  group('전등', () {
    test('꺼짐', () {
      final s = mapLightState({'power': 'off', 'brightness': 80});
      expect(s.on, isFalse);
      expect(s.brightness, 0);
    });
    test('켜짐 100%', () {
      final s = mapLightState({'power': 'on', 'brightness': 100});
      expect(s.on, isTrue);
      expect(s.brightness, 100);
      expect(s.saving, isFalse);
    });
    test('fadeout = 절전 20%', () {
      final s = mapLightState({'power': 'on', 'brightness': 100, 'mode': 'fadeout'});
      expect(s.brightness, 20);
      expect(s.saving, isTrue);
    });
    test('powerSaving 표시 · 밝기 없음 · 깜빡임', () {
      expect(mapLightState({'power': 'on'}, true).saving, isTrue);
      expect(mapLightState({'power': 'on'}).brightness, 100);
      expect(mapLightState({'power': 'on', 'brightness': 0}).brightness, 20);
      expect(mapLightState({'power': 'on', 'mode': 'blink'}).blinking, isTrue);
      expect(mapLightState({'power': 'on', 'brightness': 500}).brightness, 100);
    });
  });

  group('환풍기 풍량', () {
    test('low|mid|high ↔ 1|2|3', () {
      expect(mapSpeed('low', 2), 1);
      expect(mapSpeed('mid', 1), 2);
      expect(mapSpeed('high', 1), 3);
      expect(mapSpeed('turbo', 2), 2);
      expect(mapSpeed(null, 3), 3);
      expect(speedToBackend(1), 'low');
      expect(speedToBackend(2), 'mid');
      expect(speedToBackend(3), 'high');
      expect(speedToBackend(9), 'mid');
    });
  });

  group('공기질', () {
    test('값이 하나라도 있으면', () {
      final q = mapAirQuality({'ppm': 12, 'level': 'good'})!;
      expect(q.ppm, 12);
      expect(q.level, AirLevel.good);
      expect(mapAirQuality({'level': 'very_bad'})!.level, AirLevel.veryBad);
      expect(mapAirQuality({'level': 'VERY BAD'})!.level, AirLevel.veryBad);
      expect(mapAirQuality({'level': '매우 나쁨'})!.level, AirLevel.veryBad);
      expect(mapAirQuality({'ppm': 3.25})!.ppm, 3.25);
      expect(mapAirQuality({'ppm': -1}), isNull); // 음수는 버린다
      expect(mapAirQuality({'pm25': 40, 'pm10': 60}), isNull); // 예전 필드는 쓰지 않는다
    });
    test('모르는 등급 · 빈 값', () {
      expect(mapAirQuality({'level': 'terrible'}), isNull);
      expect(mapAirQuality({}), isNull);
      expect(mapAirQuality('x'), isNull);
    });
  });

  group('재실 판단', () {
    test('정상', () {
      final s = mapSensing({'observedAt': '2026-10-26T10:00:00Z', 'room': 'toilet', 'present': true, 'confidence': 1.4, 'activity': 'sitting', 'validSec': 5})!;
      expect(s.room, HouseRoom.bathroom);
      expect(s.present, isTrue);
      expect(s.confidence, 1);
      expect(s.activity, 'sitting');
    });
    test('시각이 없거나 잘못되면 버림', () {
      expect(mapSensing({'room': 'kitchen'}), isNull);
      expect(mapSensing({'observedAt': 'nope'}), isNull);
    });
    test('공간 없음 → 없음, 유효 시간 범위', () {
      final s = mapSensing({'observedAt': '2026-10-26T10:00:00Z', 'room': null, 'present': true, 'validSec': 99999})!;
      expect(s.present, isFalse);
      expect(s.room, isNull);
      expect(s.validSec, 600);
      expect(s.confidence, isNull);
    });
  });

  group('음성 상태', () {
    test('확인 창', () {
      final r = mapVoice({'voiceId': 'v1', 'status': 'confirm_required', 'text': ' 욕실 조명 켜줘 ', 'confirmText': '욕실 조명을 켤까요?', 'confirmDeadline': '2026-10-26T10:00:30Z'})!;
      expect(r.status, VoiceStatus.confirmRequired);
      expect(r.text, '욕실 조명 켜줘');
      expect(r.confirmText, '욕실 조명을 켤까요?');
    });
    test('모든 상태 이름', () {
      for (final s in VoiceStatus.values) {
        expect(mapVoice({'voiceId': 'v', 'status': s.wire})!.status, s);
      }
    });
    test('모르는 상태 · id 없음 · 긴 답변 자르기', () {
      expect(mapVoice({'voiceId': 'v', 'status': 'dancing'}), isNull);
      expect(mapVoice({'status': 'executed'}), isNull);
      expect(mapVoice({'voiceId': '', 'status': 'executed'}), isNull);
      expect(mapVoice({'voiceId': 'v', 'status': 'answered', 'answer': 'a' * 900})!.answer!.length, 500);
      expect(mapVoice({'voiceId': 'v', 'status': 'answered', 'answer': '   '})!.answer, isNull);
    });
  });

  group('날씨', () {
    final now = DateTime.parse('2026-10-26T10:30:00Z');
    test('시간대별: 1시간 전부터 12개, 형태가 맞는 것만', () {
      final raw = [
        for (var h = 0; h < 20; h++) {'time': DateTime.utc(2026, 10, 26, 8 + h).toIso8601String(), 'temperature': 10 + h, 'weatherCode': 3, 'precipitationProbability': h * 5},
        {'time': 'bad', 'temperature': 1},
        {'time': '2026-10-26T12:00:00Z', 'temperature': 'warm'},
      ];
      final hourly = mapHourly(raw, now)!;
      expect(hourly.length, 12);
      // 1시간 전(9:30) 보다 이른 8시 · 9시는 빠지고 10시부터
      expect(DateTime.parse(hourly.first.time), DateTime.utc(2026, 10, 26, 10));
      expect(hourly.first.temperature, 12);
      expect(hourly.first.rainChance, 10);
    });
    test('시간대별: 비어 있으면 null, code/at 별칭', () {
      expect(mapHourly([], now), isNull);
      expect(mapHourly('x', now), isNull);
      final h = mapHourly([{'at': '2026-10-26T11:00:00Z', 'temperature': 5, 'code': 61, 'rainChance': 70}], now)!;
      expect(h.single.code, 61);
      expect(h.single.rainChance, 70);
    });
    test('GET /weather', () {
      final w = mapWeather({
        'available': true,
        'stale': false,
        'text': '오늘은 맑아요',
        'weather': {'location': '서울', 'temperature': 18.6, 'condition': '맑음', 'weatherCode': 0, 'tempMax': 21, 'tempMin': 9, 'apparentTemperature': 17, 'humidity': 40, 'precipitationProbability': 10, 'hourly': [{'time': '2026-10-26T11:00:00Z', 'temperature': 19, 'weatherCode': 0}]},
      }, now)!;
      expect(w.temperature, 18.6);
      expect(w.feels, 17);
      expect(w.hourly!.length, 1);
      expect(w.text, '오늘은 맑아요');
    });
    test('받아 둔 날씨가 없거나 기온이 없으면 null', () {
      expect(mapWeather({'available': false}), isNull);
      expect(mapWeather({'available': true, 'weather': {'location': '서울'}}), isNull);
      expect(mapWeather(null), isNull);
    });
  });

  group('안전 이벤트 · 세션 · 낙상 · 정책', () {
    test('이벤트: 모르는 종류 · 필수값 없음은 버림', () {
      expect(mapEvent({'eventId': 'e', 'occurredAt': 'x', 'type': 'alien'}), isNull);
      expect(mapEvent({'type': 'auto_power_off'}), isNull);
      final e = mapEvent({'eventId': 'e', 'occurredAt': '2026-10-26T10:00:00Z', 'type': 'auto_power_off', 'room': 'kitchen', 'severity': 'danger', 'feedback': {'verdict': 'approved'}})!;
      expect(e.type, SafetyEventType.autoPowerOff);
      expect(e.severity, Severity.danger);
      expect(e.feedback!.verdict, Verdict.approved);
    });
    test('세션', () {
      final s = mapSession({'sessionId': 's', 'startedAt': '2026-10-26T10:00:00Z', 'status': 'active', 'timeline': [{'at': 'a', 'type': 't', 'summary': 'x'}, 3]})!;
      expect(s.active, isTrue);
      expect(s.timeline.length, 1);
      expect(mapSession({'sessionId': 's'}), isNull);
    });
    test('낙상: 단계 · 발송 결과', () {
      final f = mapFall({
        'incidentId': 'f1',
        'room': 'toilet',
        'status': 'pending',
        'detectedAt': '2026-10-26T10:00:00Z',
        'autoReportAt': '2026-10-26T10:01:00Z',
        'stage': 'user',
        'guardianAlertAt': '2026-10-26T10:00:30Z',
        'guardianNotified': false,
        'shutoffSent': true,
        'confidence': 0.9,
      })!;
      expect(f.room, RoomId.bathroom);
      expect(f.stage, FallStage.user);
      expect(f.guardianNotified, isFalse);
      expect(f.burnerShutOff, isTrue);
      expect(mapFall({'incidentId': 'f', 'detectedAt': 'x', 'status': 'weird'}), isNull);
      // 단계가 없으면 보호자 단계, autoReportAt 이 없으면 감지 시각
      final g = mapFall({'incidentId': 'f', 'detectedAt': 'x', 'status': 'resolved'})!;
      expect(g.stage, FallStage.guardian);
      expect(g.autoReportAt, 'x');
    });
    test('정책 · 연락처 기본값', () {
      expect(mapPolicy(null).overheatEnterC, 150);
      expect(mapPolicy({'overheatEnterC': 200}).overheatEnterC, 200);
      expect(mapFallPolicy('x').autoReportSec, 60);
      expect(mapContact({'name': '김보호'}), isNull);
      expect(mapContact({'name': '김보호', 'phone': '01000000000'})!.phone, '01000000000');
    });
    test('재실(PresenceReport): 주방 · 욕실만', () {
      expect(mapPresence({'room': 'room'}), isNull);
      final p = mapPresence({'room': 'toilet', 'present': true, 'confidence': 3, 'absentSec': -5})!;
      expect(p.room, RoomId.bathroom);
      expect(p.confidence, 1);
      expect(p.absentSec, 0);
    });
  });

  test('어떤 이상한 입력에도 예외를 던지지 않는다', () {
    final junk = <Object?>[null, 1, 'x', [], {}, {'a': null}, [null], {'observedAt': 5}, {'voiceId': 3, 'status': []}];
    for (final j in junk) {
      expect(() {
        mapSensing(j);
        mapVoice(j);
        mapEvent(j);
        mapSession(j);
        mapFall(j);
        mapWeather(j);
        mapHourly(j);
        mapAirQuality(j);
        mapBurner(j);
        mapPresence(j);
        mapPolicy(j);
        mapFallPolicy(j);
        mapContact(j);
        mapPublisher(j);
      }, returnsNormally);
    }
  });
}
