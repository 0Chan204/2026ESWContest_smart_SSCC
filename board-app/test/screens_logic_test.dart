import 'package:flutter_test/flutter_test.dart';
import 'package:homevis_gui/data/parse.dart';
import 'package:homevis_gui/features/alerts/fall_alert_sheet.dart';
import 'package:homevis_gui/features/history/history_page.dart';
import 'package:homevis_gui/features/weather/weather_sheet.dart';
import 'package:homevis_gui/models/types.dart';
import 'package:homevis_gui/util/device_text.dart';
import 'package:homevis_gui/util/format.dart';
import 'package:homevis_gui/util/labels.dart';

import 'fixtures.dart';

FallIncident fall({bool notified = false, String stage = 'guardian', String status = 'pending'}) => mapFall({
      'incidentId': 'f',
      'status': status,
      'detectedAt': '2026-10-26T10:00:00Z',
      'autoReportAt': '2026-10-26T10:01:00Z',
      'stage': stage,
      'guardianAlertAt': '2026-10-26T10:00:30Z',
      'guardianNotified': notified,
    })!;

void main() {
  group('낙상 경보 문자 줄 (실제 발송 결과만)', () {
    const g = Contact(name: '김보호', phone: '01012345678');
    test('보냄', () {
      final l = fallSmsLine(fall(notified: true), g);
      expect(l.kind, 'ok');
      expect(l.text, '보호자 김보호님(010-****-5678)께 문자를 보냈어요');
    });
    test('본인 응답 대기 → 보호자 알림까지 카운트다운', () {
      final l = fallSmsLine(fall(stage: 'user'), g);
      expect(l.kind, 'wait');
      expect(l.countdownTo, '2026-10-26T10:00:30Z');
    });
    test('연락처 없음 · 발송 실패', () {
      expect(fallSmsLine(fall(), null).text, '보호자 연락처가 없어 문자를 못 보냈어요');
      expect(fallSmsLine(fall(), g).text, '보호자에게 문자를 보내지 못했어요');
      // 끝난 사건은 본인 단계여도 대기 문장을 쓰지 않는다
      expect(fallSmsLine(fall(stage: 'user', status: 'resolved'), g).kind, 'warn');
    });
  });

  group('기록 거르기', () {
    final now = DateTime(2026, 10, 26, 12);
    String iso(DateTime d) => d.toUtc().toIso8601String();
    final events = [
      mapEvent(eventJson('a', 'auto_power_off', at: iso(DateTime(2026, 10, 26, 9))))!,
      mapEvent(eventJson('b', 'fall_detected', room: 'toilet', at: iso(DateTime(2026, 10, 24, 9))))!,
      mapEvent(eventJson('c', 'auto_dispense', at: iso(DateTime(2026, 10, 10, 7))))!,
      mapEvent(eventJson('d', 'cooking_started', at: iso(DateTime(2026, 10, 26, 8))))!, // 기록 대상 아님
    ];
    test('기간', () {
      expect(filterRecords(events, period: Period.today, now: now).map((e) => e.eventId), ['a']);
      expect(filterRecords(events, period: Period.week, now: now).map((e) => e.eventId), ['a', 'b']);
      expect(filterRecords(events, period: Period.month, now: now).map((e) => e.eventId), ['a', 'b', 'c']);
    });
    test('분류 · 공간', () {
      expect(filterRecords(events, period: Period.month, category: EventCategory.fall, now: now).single.eventId, 'b');
      expect(filterRecords(events, period: Period.month, category: EventCategory.routine, now: now).single.eventId, 'c');
      expect(filterRecords(events, period: Period.month, room: RoomId.bathroom, now: now).single.eventId, 'b');
    });
    test('날짜 묶음 제목', () {
      expect(dayTitle('2026-10-26', now), '오늘');
      expect(dayTitle('2026-10-25', now), '어제');
      expect(dayTitle('2026-10-15', now), '10월 15일 목요일');
    });
  });

  group('날씨 안내 한 줄', () {
    final now = DateTime.parse('2026-10-26T10:00:00Z');
    test('처음 비 오는 시각', () {
      final hourly = [
        const HourlyWeather(time: '2026-10-26T10:00:00Z', temperature: 18, code: 0, rainChance: 0),
        const HourlyWeather(time: '2026-10-26T15:00:00Z', temperature: 16, code: 61, rainChance: 70),
      ];
      expect(rainLine(hourly, now), contains('부터 비 소식이 있어요'));
      expect(rainLine([hourly[1]], DateTime.parse('2026-10-26T14:30:00Z')), startsWith('지금 비 소식'));
      expect(rainLine([hourly[0]], now), isNull);
      expect(rainLine(null, now), isNull);
    });
  });

  group('글자 · 해석', () {
    test('시간 글자', () {
      expect(formatDuration(45), '45초');
      expect(formatDuration(80), '1분 20초');
      expect(formatDuration(720), '12분');
      expect(formatCountdown(65.2), '01:06');
      expect(formatCountdown(-3), '00:00');
      expect(agoShort('2026-10-26T10:00:00Z', DateTime.parse('2026-10-26T10:00:12Z')), '12초 전');
    });
    test('행동 · 신호', () {
      expect(activityLabel('sitting'), '앉아 있음');
      expect(activityLabel('none'), isNull);
      expect(activityLabel('<b>x</b>'), '동작 확인 중');
      expect(rssiBars(-50), 4);
      expect(rssiBars(-80), 1);
      expect(rssiBars(null), 0);
    });
    test('재실 판단 신선도 · 공간별 그래프', () {
      final now = DateTime.parse('2026-10-26T10:00:10Z');
      final s = mapSensing({'observedAt': '2026-10-26T10:00:05Z', 'room': 'kitchen', 'present': true, 'confidence': 0.9, 'validSec': 5})!;
      expect(isFresh(s, now), isTrue);
      expect(isFresh(s, now.add(const Duration(seconds: 10))), isFalse);
      final v = roomPresence(s, HouseRoom.kitchen, now);
      expect(v.percent, 90);
      expect(roomPresence(s, HouseRoom.bedroom, now).present, isFalse);
      expect(roomSeries([s], HouseRoom.kitchen, now), [90]);
      expect(roomSeries([s], HouseRoom.bathroom, now), [0]);
    });
    test('밝기 단계 · 전화번호 가리기', () {
      expect(snapBrightness(14, [0, 20, 100]), 20);
      expect(snapBrightness(64), 60);
      expect(brightnessLabel(0), '꺼짐');
      expect(brightnessLabel(20, 20), '절전 20%');
      expect(maskPhone('01012345678'), '010-****-5678');
    });
  });
}
