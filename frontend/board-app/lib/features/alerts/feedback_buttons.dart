import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../../models/types.dart';
import '../../store/home_store.dart';
import '../../theme/theme.dart';
import '../../ui/icons.dart';
import '../../ui/widgets.dart';

/// 자동 조치 적절성 피드백 (React FeedbackButtons). 판단 기준을 다듬는 근거 데이터가 된다.
class FeedbackButtons extends StatefulWidget {
  const FeedbackButtons({super.key, required this.event, this.large = false});
  final SafetyEvent event;
  final bool large;

  @override
  State<FeedbackButtons> createState() => _FeedbackButtonsState();
}

class _FeedbackButtonsState extends State<FeedbackButtons> {
  bool _busy = false;

  Future<void> _send(Verdict v) async {
    setState(() => _busy = true);
    try {
      await context.read<HomeStore>().submitFeedback(widget.event.eventId, v);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final c = context.hv;
    final done = widget.event.feedback;
    if (done != null) {
      return Padding(
        padding: const EdgeInsets.symmetric(horizontal: 16),
        child: Text(
          '${done.verdict == Verdict.approved ? '“적절했어요”' : '“과했어요”'} 로 남겼어요. 판단 기준을 다듬는 데 참고할게요.',
          style: ts(14, color: c.ink3, height: 1.45),
        ),
      );
    }
    final size = widget.large ? BtnSize.xl : BtnSize.lg;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      mainAxisSize: MainAxisSize.min,
      children: [
        Padding(
          padding: const EdgeInsets.fromLTRB(16, 0, 16, 6),
          child: Text('이 조치가 적절했나요?', style: ts(13, weight: w500, color: c.ink3)),
        ),
        Row(
          children: [
            Expanded(
              child: HvButton(
                label: '적절했어요',
                icon: Ic.thumbsUp,
                variant: BtnVariant.plain,
                size: size,
                expand: true,
                onPressed: _busy ? null : () => _send(Verdict.approved),
              ),
            ),
            const SizedBox(width: 8),
            Expanded(
              child: HvButton(
                label: '과했어요',
                icon: Ic.thumbsDown,
                variant: BtnVariant.plain,
                size: size,
                expand: true,
                onPressed: _busy ? null : () => _send(Verdict.rejected),
              ),
            ),
          ],
        ),
      ],
    );
  }
}
