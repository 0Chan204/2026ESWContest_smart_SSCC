import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../../models/types.dart';
import '../../store/home_state.dart';
import '../../store/home_store.dart';
import '../../theme/theme.dart';
import '../../ui/sheet.dart';
import '../../ui/widgets.dart';
import '../../util/format.dart';
import '../../util/labels.dart';
import '../alerts/feedback_buttons.dart';
import 'event_row.dart';
import 'session_timeline.dart';

/// 기록 상세: 무슨 일이 있었고, 왜 그렇게 판단했고, 무엇을 했는지 (React EventDetailSheet)
class EventDetailSheet extends StatelessWidget {
  const EventDetailSheet({super.key, required this.eventId});
  final String eventId;

  @override
  Widget build(BuildContext context) {
    final state = context.select<HomeStore, HomeState>((s) => s.state);
    final elderly = context.elderly;
    final c = context.hv;
    void close() => Navigator.of(context).maybePop();
    final e = state.eventById(eventId);
    if (e == null) return SheetFrame(onClose: close, variant: SheetVariant.side, child: const SizedBox.shrink());
    final session = e.sessionId != null ? state.sessions[e.sessionId] : null;
    const gap = SizedBox(height: 24);
    final paras = <Widget>[
      if (!elderly && e.trigger != null) _Para(k: '감지', v: e.trigger!),
      if (e.action != null) _Para(k: '조치', v: e.action!, big: elderly),
      if (!elderly && e.reasoning != null) _Para(k: '판단 근거', v: e.reasoning!),
    ];
    String? sessionTitle;
    if (session != null) {
      final end = session.endedAt != null ? DateTime.tryParse(session.endedAt!) : null;
      final start = DateTime.tryParse(session.startedAt);
      final dur = end != null && start != null ? ' · ${formatDuration(end.difference(start).inSeconds)}' : '';
      sessionTitle = '조리 흐름 · 최고 ${session.peakTemperature.round()}°C$dur';
    }

    return SheetFrame(
      onClose: close,
      variant: SheetVariant.side,
      width: elderly ? 600 : 480,
      title: eventTitle[e.type],
      subtitle: Text('${roomLabel[e.room]} · ${formatDateTime(e.occurredAt)}'),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          if (e.guidance != null)
            Container(
              padding: const EdgeInsets.all(16),
              decoration: BoxDecoration(color: c.surface, borderRadius: BorderRadius.circular(18)),
              child: Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  EventIcon(event: e),
                  const SizedBox(width: 12),
                  Expanded(child: Text(e.guidance!, style: ts(elderly ? 20 : 16, color: c.ink, height: 1.6))),
                ],
              ),
            ),
          if (e.guidance != null) gap,
          ListGroup(children: [
            ListRow(big: elderly, title: '분류', value: categoryLabel[eventCategory(e.type)]),
            if (e.temperature != null) ListRow(big: elderly, title: '온도', value: '${e.temperature!.round()}°C'),
            if (e.feedback != null)
              ListRow(big: elderly, title: '피드백', value: e.feedback!.verdict == Verdict.approved ? '적절했어요' : '과했어요'),
          ]),
          if (paras.isNotEmpty) ...[gap, ListGroup(children: paras)],
          if (feedbackTypes.contains(e.type)) ...[gap, FeedbackButtons(event: e, large: elderly)],
          if (session != null) ...[
            gap,
            ListGroup(
              title: sessionTitle,
              bodyPadding: const EdgeInsets.fromLTRB(16, 16, 16, 0),
              children: [SessionTimeline(session: session, big: elderly)],
            ),
          ],
        ],
      ),
    );
  }
}

/// 긴 글 한 칸 (제목 위, 내용 아래)
class _Para extends StatelessWidget {
  const _Para({required this.k, required this.v, this.big = false});
  final String k;
  final String v;
  final bool big;

  @override
  Widget build(BuildContext context) {
    final c = context.hv;
    return Padding(
      padding: const EdgeInsets.only(left: 16),
      child: RowSeparator(
        child: Padding(
          padding: const EdgeInsets.fromLTRB(0, 12, 16, 12),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(k, style: ts(13, color: c.ink3)),
              const SizedBox(height: 2),
              Text(v, style: ts(big ? 20 : 15, color: c.ink, height: 1.6)),
            ],
          ),
        ),
      ),
    );
  }
}
