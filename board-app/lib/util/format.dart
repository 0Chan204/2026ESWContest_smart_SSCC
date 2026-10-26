// 시각 · 시간 글자 (React src/lib/format.ts 와 같은 결과)

String _p(int n) => n.toString().padLeft(2, '0');

DateTime? _local(String iso) => DateTime.tryParse(iso)?.toLocal();

/// ISO → 2026.10.03 14:32
String formatDateTime(String iso) {
  final d = _local(iso);
  if (d == null) return iso;
  return '${d.year}.${_p(d.month)}.${_p(d.day)} ${_p(d.hour)}:${_p(d.minute)}';
}

/// ISO → 14:32
String formatTime(String iso) {
  final d = _local(iso);
  if (d == null) return iso;
  return '${_p(d.hour)}:${_p(d.minute)}';
}

DateTime _day(DateTime d) => DateTime(d.year, d.month, d.day);

/// ISO → "오늘 14:32" / "어제 18:29" / "10월 1일 07:42"
String formatWhen(String iso, [DateTime? now]) {
  final d = _local(iso);
  if (d == null) return iso;
  final today = _day(now ?? DateTime.now());
  final diff = today.difference(_day(d)).inHours / 24;
  final t = formatTime(iso);
  if (diff.round() == 0) return '오늘 $t';
  if (diff.round() == 1) return '어제 $t';
  return '${d.month}월 ${d.day}일 $t';
}

/// ISO → "방금" / "3분 전" / "2시간 전"
String formatAgo(String iso, [DateTime? now]) {
  final d = DateTime.tryParse(iso);
  if (d == null) return iso;
  final ms = (now ?? DateTime.now()).millisecondsSinceEpoch - d.millisecondsSinceEpoch;
  final sec = ms < 0 ? 0 : (ms / 1000).round();
  if (sec < 30) return '방금';
  if (sec < 3600) return '${(sec / 60).round() < 1 ? 1 : (sec / 60).round()}분 전';
  if (sec < 86400) return '${(sec / 3600).round()}시간 전';
  return '${(sec / 86400).round()}일 전';
}

/// 방금 · n초 전 (1분이 넘으면 n분 전) — 재실 감지 화면용
String agoShort(String iso, DateTime now) {
  final d = DateTime.tryParse(iso);
  if (d == null) return iso;
  final ms = now.millisecondsSinceEpoch - d.millisecondsSinceEpoch;
  final sec = ms < 0 ? 0 : (ms / 1000).round();
  if (sec < 2) return '방금';
  if (sec < 60) return '$sec초 전';
  return formatAgo(iso, now);
}

/// 초 → "1분 20초" / "12분" / "45초"
String formatDuration(num totalSec) {
  final s = totalSec.isFinite ? (totalSec < 0 ? 0 : totalSec.round()) : 0;
  final m = s ~/ 60;
  final r = s % 60;
  if (m == 0) return '$r초';
  if (m >= 10 || r == 0) return '$m분';
  return '$m분 $r초';
}

/// 초 → 00:45
String formatCountdown(num totalSec) {
  final s = totalSec.isFinite ? (totalSec <= 0 ? 0 : totalSec.ceil()) : 0;
  return '${_p(s ~/ 60)}:${_p(s % 60)}';
}

const _days = ['월', '화', '수', '목', '금', '토', '일'];

/// Date → 10월 3일 금요일
String formatToday(DateTime d) => '${d.month}월 ${d.day}일 ${_days[d.weekday - 1]}요일';

String formatClock(DateTime d) => '${_p(d.hour)}:${_p(d.minute)}';

/// 로컬 날짜 키 YYYY-MM-DD
String dayKey(DateTime d) => '${d.year}-${_p(d.month)}-${_p(d.day)}';

String localDayOf(String iso) {
  final d = _local(iso);
  return d == null ? '' : dayKey(d);
}

/// 시간대가 붙은 ISO (예: 2026-10-24T21:00:00+09:00). 음성 명령 recognizedAt 용
String isoWithOffset([DateTime? at]) {
  final d = at ?? DateTime.now();
  final off = d.timeZoneOffset.inMinutes;
  final a = off.abs();
  return '${d.year}-${_p(d.month)}-${_p(d.day)}T${_p(d.hour)}:${_p(d.minute)}:${_p(d.second)}'
      '${off >= 0 ? '+' : '-'}${_p(a ~/ 60)}:${_p(a % 60)}';
}

/// 오후 3시 / 오전 9시
String koreanHour(String iso) {
  final d = _local(iso);
  if (d == null) return iso;
  final h = d.hour;
  return '${h < 12 ? '오전' : '오후'} ${h % 12 == 0 ? 12 : h % 12}시';
}

/// 남은 초 (음수 가능)
double secondsUntil(String iso, DateTime now) {
  final d = DateTime.tryParse(iso);
  if (d == null) return 0;
  return (d.millisecondsSinceEpoch - now.millisecondsSinceEpoch) / 1000;
}
