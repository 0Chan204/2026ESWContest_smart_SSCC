import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../../models/types.dart';
import '../../store/home_state.dart';
import '../../store/home_store.dart';
import '../../store/speaker.dart';
import '../../theme/theme.dart';
import '../../ui/icons.dart';
import '../../ui/sheet.dart';
import '../../ui/widgets.dart';
import '../../util/format.dart';
import '../../util/labels.dart';
import 'feedback_buttons.dart';

/// 시스템이 방금 수행한 안전 조치 안내 (React ActionNoticeSheet).
/// 조치는 서버가 먼저 수행하고 결과를 통보하므로, 여기서는 "무엇을 왜 했는지"를 알린다.
class ActionNoticeLayer extends StatefulWidget {
  const ActionNoticeLayer({super.key});

  @override
  State<ActionNoticeLayer> createState() => _ActionNoticeLayerState();
}

class _ActionNoticeLayerState extends State<ActionNoticeLayer> {
  String? _spokenFor;

  @override
  Widget build(BuildContext context) {
    final state = context.select<HomeStore, HomeState>((s) => s.state);
    final notice = state.notice;
    if (notice == null) return const SizedBox.shrink();
    if (_spokenFor != notice.eventId) {
      _spokenFor = notice.eventId;
      final speaker = context.read<Speaker>();
      WidgetsBinding.instance.addPostFrameCallback((_) => speaker.speak(notice.guidance));
    }
    // 피드백 반영을 위해 최신 이벤트 객체를 다시 찾는다
    final event = state.eventById(notice.eventId) ?? notice;
    final store = context.read<HomeStore>();
    final elderly = context.elderly;
    final c = context.hv;
    final danger = event.severity == Severity.danger;
    final icon = event.type == SafetyEventType.overheatDetected
        ? Ic.flame
        : event.type == SafetyEventType.autoPowerOff
            ? Ic.power
            : Ic.gauge;
    final details = <(String, String)>[
      if (event.trigger != null) ('감지', event.trigger!),
      if (event.action != null) ('조치', event.action!),
      if (event.reasoning != null) ('판단 근거', event.reasoning!),
    ];

    return ModalLayer(
      onBarrierTap: store.dismissNotice,
      child: SheetFrame(
        onClose: store.dismissNotice,
        hideClose: true,
        width: elderly ? 620 : 480,
        footer: HvButton(
          label: '확인',
          variant: BtnVariant.primary,
          size: elderly ? BtnSize.xl : BtnSize.lg,
          expand: true,
          onPressed: store.dismissNotice,
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            const SizedBox(height: 16),
            Icon(icon, size: elderly ? 56 : 48, color: danger ? c.danger : c.warn),
            const SizedBox(height: 12),
            Text(eventTitle[event.type]!,
                textAlign: TextAlign.center, style: ts(elderly ? 30 : 24, weight: w700, color: c.ink, height: 1.25)),
            const SizedBox(height: 2),
            Text('주방 · ${formatTime(event.occurredAt)}', textAlign: TextAlign.center, style: ts(14, color: c.ink3)),
            if (event.guidance != null)
              Padding(
                padding: const EdgeInsets.only(top: 16),
                child: Text(event.guidance!,
                    textAlign: TextAlign.center, style: ts(elderly ? 20 : 17, color: c.ink, height: 1.6)),
              ),
            if (!elderly && details.isNotEmpty)
              Padding(
                padding: const EdgeInsets.only(top: 24),
                child: ListGroup(children: [for (final (k, v) in details) _KvRow(k: k, v: v)]),
              ),
            if (feedbackTypes.contains(event.type))
              Padding(padding: const EdgeInsets.only(top: 24), child: FeedbackButtons(event: event, large: elderly)),
          ],
        ),
      ),
    );
  }
}

class _KvRow extends StatelessWidget {
  const _KvRow({required this.k, required this.v});
  final String k;
  final String v;

  @override
  Widget build(BuildContext context) {
    final c = context.hv;
    return Padding(
      padding: const EdgeInsets.only(left: 16),
      child: RowSeparator(
        child: Padding(
          padding: const EdgeInsets.fromLTRB(0, 12, 16, 12),
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              SizedBox(width: 80, child: Text(k, style: ts(15, color: c.ink2))),
              const SizedBox(width: 16),
              Expanded(child: Text(v, style: ts(15, color: c.ink, height: 1.45))),
            ],
          ),
        ),
      ),
    );
  }
}
