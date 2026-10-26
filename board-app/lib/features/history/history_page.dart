import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../../app/page_header.dart';
import '../../models/types.dart';
import '../../store/home_store.dart';
import '../../theme/theme.dart';
import '../../ui/icons.dart';
import '../../ui/widgets.dart';
import '../../util/format.dart';
import '../../util/labels.dart';
import 'event_row.dart';

enum Period { today, week, month }

const periodDays = {Period.today: 1, Period.week: 7, Period.month: 30};

/// 기간 첫날 (로컬 날짜 키). 오늘 = 오늘, 7일 = 오늘 포함 7일
String periodFrom(Period p, DateTime now) => dayKey(DateTime(now.year, now.month, now.day - (periodDays[p]! - 1)));

/// 기록 거르기 (React HistoryPage 의 filtered — 검색어 · 날짜 입력 대신 기간 버튼)
List<SafetyEvent> filterRecords(
  List<SafetyEvent> events, {
  EventCategory? category,
  RoomId? room,
  Period period = Period.week,
  DateTime? now,
}) {
  final from = periodFrom(period, now ?? DateTime.now());
  return [
    for (final e in events)
      if (isRecord(e) &&
          (category == null || eventCategory(e.type) == category) &&
          (room == null || e.room == room) &&
          localDayOf(e.occurredAt).compareTo(from) >= 0)
        e,
  ];
}

/// 날짜 묶음 제목: 오늘 / 어제 / 10월 15일 수요일
String dayTitle(String day, DateTime now) {
  if (day == dayKey(now)) return '오늘';
  if (day == dayKey(DateTime(now.year, now.month, now.day - 1))) return '어제';
  final d = DateTime.tryParse('${day}T00:00:00');
  if (d == null) return day;
  return formatToday(d);
}

/// 안전 기록 (React HistoryPage). 보드는 키보드가 없어 검색 · 날짜 입력 대신 분류 · 공간 · 기간 버튼과 쪽 넘김만 둔다.
class HistoryPage extends StatefulWidget {
  const HistoryPage({super.key});

  @override
  State<HistoryPage> createState() => _HistoryPageState();
}

class _HistoryPageState extends State<HistoryPage> {
  EventCategory? _category;
  RoomId? _room;
  Period _period = Period.week;
  int _page = 1;

  void _update(VoidCallback fn) => setState(() {
        fn();
        _page = 1; // 조건이 바뀌면 1쪽으로
      });

  @override
  Widget build(BuildContext context) {
    final c = context.hv;
    final elderly = context.elderly;
    final short = MediaQuery.sizeOf(context).height <= 760;
    final events = context.select<HomeStore, List<SafetyEvent>>((s) => s.state.events);
    final now = DateTime.now();
    // 세로가 짧은 월패드(1280×720)에서 어르신 글자가 크면 한 쪽에 3건만
    final perPage = elderly ? (short ? 3 : 4) : 6;
    final filtered = filterRecords(events, category: _category, room: _room, period: _period, now: now);
    final totalPages = filtered.isEmpty ? 1 : (filtered.length / perPage).ceil();
    final current = _page.clamp(1, totalPages);
    final items = filtered.skip((current - 1) * perPage).take(perPage).toList();
    final groups = <String, List<SafetyEvent>>{};
    for (final e in items) {
      (groups[localDayOf(e.occurredAt)] ??= []).add(e);
    }

    final records = events.where(isRecord).toList();
    final weekFrom = periodFrom(Period.week, now);
    final week = records.where((e) => localDayOf(e.occurredAt).compareTo(weekFrom) >= 0).toList();
    final fire = week.where((e) => eventCategory(e.type) == EventCategory.fire).length;
    final falls = week.where((e) => e.type == SafetyEventType.fallDetected).length;
    final routine = week.where((e) => eventCategory(e.type) == EventCategory.routine).length;
    final waiting = records.where((e) => feedbackTypes.contains(e.type) && e.feedback == null).length;
    final segSize = elderly ? SegSize.lg : SegSize.md;

    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        const PageHeader(title: '안전 기록'),
        Padding(
          padding: EdgeInsets.fromLTRB(32, short ? 16 : 20, 32, 0),
          child: Row(
            children: [
              Expanded(
                flex: 38,
                child: Segmented<EventCategory?>(
                  size: segSize,
                  value: _category,
                  options: [
                    const SegOption(null, '전체'),
                    for (final cat in EventCategory.values) SegOption(cat, categoryLabel[cat]!),
                  ],
                  onChanged: (v) => _update(() => _category = v),
                ),
              ),
              const SizedBox(width: 12),
              Expanded(
                flex: 34,
                child: Segmented<RoomId?>(
                  size: segSize,
                  value: _room,
                  options: const [
                    SegOption(null, '모든 공간'),
                    SegOption(RoomId.kitchen, '주방'),
                    SegOption(RoomId.bedroom, '침실'),
                    SegOption(RoomId.bathroom, '욕실'),
                  ],
                  onChanged: (v) => _update(() => _room = v),
                ),
              ),
              const SizedBox(width: 12),
              Expanded(
                flex: 24,
                child: Segmented<Period>(
                  size: segSize,
                  value: _period,
                  options: const [SegOption(Period.today, '오늘'), SegOption(Period.week, '7일'), SegOption(Period.month, '30일')],
                  onChanged: (v) => _update(() => _period = v),
                ),
              ),
            ],
          ),
        ),
        Expanded(
          child: Padding(
            padding: EdgeInsets.fromLTRB(32, short ? 16 : 20, 32, short ? 20 : 28),
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                Expanded(
                  flex: 8,
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.stretch,
                    children: [
                      Expanded(
                        child: items.isEmpty
                            ? HvCard(
                                child: Center(
                                  child: Column(
                                    mainAxisSize: MainAxisSize.min,
                                    children: [
                                      Icon(Ic.records, size: 32, color: c.ink3),
                                      const SizedBox(height: 8),
                                      Text('조건에 맞는 기록 없음', style: ts(15, color: c.ink3)),
                                    ],
                                  ),
                                ),
                              )
                            // 한 쪽 분량이라 대개 다 들어간다. 글자를 키워 넘칠 때만 칸 안에서 밀린다
                            : SingleChildScrollView(
                                physics: const ClampingScrollPhysics(),
                                child: Column(
                                  crossAxisAlignment: CrossAxisAlignment.stretch,
                                  children: [
                                    for (final (i, entry) in groups.entries.indexed) ...[
                                      if (i > 0) const SizedBox(height: 20),
                                      ListGroup(
                                        title: dayTitle(entry.key, now),
                                        children: [for (final e in entry.value) EventRow(event: e, big: elderly, timeOnly: true)],
                                      ),
                                    ],
                                  ],
                                ),
                              ),
                      ),
                      Padding(
                        padding: const EdgeInsets.only(top: 8),
                        child: SizedBox(
                          height: 48,
                          child: Row(
                            children: [
                              SizedBox(width: 72, child: Text('${filtered.length}건', style: ts(13, color: c.ink3))),
                              Expanded(
                                child: Center(
                                  child: _Pagination(page: current, totalPages: totalPages, onChange: (n) => setState(() => _page = n)),
                                ),
                              ),
                              const SizedBox(width: 72),
                            ],
                          ),
                        ),
                      ),
                    ],
                  ),
                ),
                const SizedBox(width: 24),
                Expanded(
                  flex: 4,
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.stretch,
                    children: [
                      const SectionTitle(title: '최근 7일'),
                      ListGroup(
                        footer: waiting > 0 && !elderly ? '자동 조치가 적절했는지 알려주시면 판단 기준을 다듬는 데 쓰여요.' : null,
                        children: [
                          ListRow(big: elderly, title: '화재 예방 조치', value: '$fire건'),
                          ListRow(big: elderly, title: '낙상 감지', value: '$falls건'),
                          ListRow(big: elderly, title: '아침 자동 출수', value: '$routine건'),
                          if (waiting > 0 && !elderly)
                            ListRow(
                              title: '피드백 대기',
                              valueWidget: Text('$waiting건', style: ts(15, weight: w600, color: c.brandInk, tabular: true)),
                            ),
                        ],
                      ),
                    ],
                  ),
                ),
              ],
            ),
          ),
        ),
      ],
    );
  }
}

/// 쪽 넘김 (React Pagination). 쪽이 많으면 지금 쪽 주변만
class _Pagination extends StatelessWidget {
  const _Pagination({required this.page, required this.totalPages, required this.onChange});
  final int page;
  final int totalPages;
  final ValueChanged<int> onChange;

  @override
  Widget build(BuildContext context) {
    if (totalPages <= 1) return const SizedBox.shrink();
    final c = context.hv;
    var start = (page - 2).clamp(1, totalPages);
    final end = (start + 4).clamp(1, totalPages);
    start = (end - 4).clamp(1, totalPages);
    Widget btn({required Widget child, VoidCallback? onTap, bool selected = false, String? label}) => Opacity(
          opacity: onTap == null && !selected ? 0.3 : 1,
          child: Pressable(
            onTap: onTap,
            semanticLabel: label,
            child: Container(
              constraints: const BoxConstraints(minWidth: 48, minHeight: 48),
              padding: const EdgeInsets.symmetric(horizontal: 12),
              alignment: Alignment.center,
              decoration: BoxDecoration(color: selected ? c.fill : Colors.transparent, borderRadius: BorderRadius.circular(14)),
              child: child,
            ),
          ),
        );
    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        btn(
          label: '이전 쪽',
          onTap: page > 1 ? () => onChange(page - 1) : null,
          child: Icon(Ic.chevronLeft, size: 20, color: c.brandInk),
        ),
        for (var n = start; n <= end; n++)
          btn(
            label: '$n쪽',
            selected: n == page,
            onTap: n == page ? null : () => onChange(n),
            child: Text('$n', style: ts(14, weight: w600, color: n == page ? c.ink : c.ink2, tabular: true)),
          ),
        btn(
          label: '다음 쪽',
          onTap: page < totalPages ? () => onChange(page + 1) : null,
          child: Icon(Ic.chevronRight, size: 20, color: c.brandInk),
        ),
      ],
    );
  }
}
