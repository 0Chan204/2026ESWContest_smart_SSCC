import 'package:flutter_test/flutter_test.dart';
import 'package:homevis_gui/util/phone.dart';

void main() {
  test('normalizePhone: 백엔드 _normalize_phone 과 같은 규칙 (숫자만 9~11자리, 0 시작)', () {
    expect(normalizePhone('010-1234-5678'), '01012345678');
    expect(normalizePhone('010 1234 5678'), '01012345678');
    expect(normalizePhone('0212345678'), '0212345678');
    expect(normalizePhone('021234567'), '021234567');
    expect(normalizePhone('01012345'), isNull); // 8자리
    expect(normalizePhone('010123456789'), isNull); // 12자리
    expect(normalizePhone('11012345678'), isNull); // 0 으로 시작하지 않음
    expect(normalizePhone(''), isNull);
  });

  test('formatPhoneLive: 누르는 동안 앞에서부터 묶기', () {
    expect(formatPhoneLive(''), '');
    expect(formatPhoneLive('010'), '010');
    expect(formatPhoneLive('0101'), '010-1');
    expect(formatPhoneLive('0101234'), '010-1234');
    expect(formatPhoneLive('01012345'), '010-1234-5');
    expect(formatPhoneLive('0101234567'), '010-1234-567');
    expect(formatPhoneLive('01012345678'), '010-1234-5678');
    expect(formatPhoneLive('0311234567'), '031-123-4567');
    expect(formatPhoneLive('021234567'), '02-123-4567');
    expect(formatPhoneLive('0212345678'), '02-1234-5678');
  });

  test('formatPhone · maskPhone (공용 화면은 가운데를 가린다)', () {
    expect(formatPhone('01012345678'), '010-1234-5678');
    expect(formatPhone('0311234567'), '031-123-4567');
    expect(maskPhone('01012345678'), '010-****-5678');
    expect(maskPhone('0311234567'), '031-***-4567');
    expect(maskPhone('021234567'), '*****4567');
  });
}
