import 'package:flutter/material.dart';

import '../../models/types.dart';
import '../../theme/theme.dart';
import '../../ui/icons.dart';
import '../../ui/sheet.dart';
import '../../ui/widgets.dart';
import '../../util/format.dart';
import '../../util/labels.dart';
import 'event_detail_sheet.dart';

/// 기록 아이콘: iOS 알림 목록처럼 색 사각형 (위험 빨강 · 경고 주황 · 생활 파랑 · 그 외 회색)
class EventIcon extends StatelessWidget {
  const EventIcon({super.key, required this.event});
  final SafetyEvent event;

  @override
  Widget build(BuildContext context) {
    final cat = eventCategory(event.type);
    final icon = switch (cat) { EventCategory.fire => Ic.flame, EventCategory.fall => Ic.personStanding, EventCategory.routine => Ic.water };
    final color = event.severity == Severity.danger
        ? SymColor.red
        : event.severity == Severity.warning
            ? SymColor.orange
            : cat == EventCategory.routine
                ? SymColor.blue
                : SymColor.gray;
    return SymbolIcon(icon: icon, color: color);
  }
}

void openEventSheet(BuildContext context, String eventId) =>
    showSheet(context, (_) => EventDetailSheet(eventId: eventId), variant: SheetVariant.side);

/// 안전 기록 한 줄. compact = 좁은 칸(주방 · 욕실 오른쪽)용, timeOnly = 날짜별 묶음 안
class EventRow extends StatelessWidget {
  const EventRow({super.key, required this.event, this.big = false, this.compact = false, this.timeOnly = false});
  final SafetyEvent event;
  final bool big;
  final bool compact;
  final bool timeOnly;

  @override
  Widget build(BuildContext context) {
    final e = event;
    final when = timeOnly ? formatTime(e.occurredAt) : formatWhen(e.occurredAt);
    final action = e.action != null ? ' · ${e.action}' : '';
    return ListRow(
      big: big,
      chevron: true,
      onTap: () => openEventSheet(context, e.eventId),
      leading: EventIcon(event: e),
      title: eventTitle[e.type]!,
      titleWeight: w500,
      subtitle: compact ? '$when$action' : '${roomLabel[e.room]}$action',
      value: compact ? null : when,
    );
  }
}
