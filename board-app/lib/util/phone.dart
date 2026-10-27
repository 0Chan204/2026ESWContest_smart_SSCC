// 전화번호 검증 · 표시 (React src/lib/phone.ts 와 같은 규칙).
// 백엔드 schemas._normalize_phone 과 같다: 숫자만 남겨 9~11자리, 0 으로 시작.

/// 저장 가능한 번호면 숫자만 돌려준다. 아니면 null
String? normalizePhone(String value) {
  final digits = value.replaceAll(RegExp(r'\D'), '');
  if (digits.length < 9 || digits.length > 11 || !digits.startsWith('0')) return null;
  return digits;
}

/// 01012345678 → 010-1234-5678 (다 입력된 번호)
String formatPhone(String digits) {
  if (digits.length == 11) return '${digits.substring(0, 3)}-${digits.substring(3, 7)}-${digits.substring(7)}';
  if (digits.length == 10) return '${digits.substring(0, 3)}-${digits.substring(3, 6)}-${digits.substring(6)}';
  return digits;
}

/// 누르는 동안 보여줄 모양 (010-1234-5 처럼 앞에서부터 묶는다). 서울 02 는 2자리로 끊는다
String formatPhoneLive(String input) {
  final d = input.replaceAll(RegExp(r'\D'), '');
  if (d.startsWith('02')) {
    if (d.length <= 2) return d;
    if (d.length <= 5) return '02-${d.substring(2)}';
    if (d.length <= 9) return '02-${d.substring(2, 5)}-${d.substring(5)}';
    return '02-${d.substring(2, 6)}-${d.substring(6)}';
  }
  if (d.length <= 3) return d;
  if (d.length <= 7) return '${d.substring(0, 3)}-${d.substring(3)}';
  // 10자리는 010 이 아니면 3-3-4 (예: 031-123-4567), 010 은 11자리를 기다리는 중
  if (d.length == 10 && !d.startsWith('010')) return '${d.substring(0, 3)}-${d.substring(3, 6)}-${d.substring(6)}';
  final end = d.length > 11 ? 11 : d.length;
  return '${d.substring(0, 3)}-${d.substring(3, 7)}-${d.substring(7, end)}';
}

/// 화면 표시용 마스킹: 010-****-5678 (보드는 여러 사람이 보는 공용 화면)
String maskPhone(String digits) {
  final f = formatPhone(digits);
  final parts = f.split('-');
  if (parts.length == 3) return '${parts[0]}-${'*' * parts[1].length}-${parts[2]}';
  return f.replaceAllMapped(RegExp(r'\d(?=\d{4})'), (_) => '*');
}
