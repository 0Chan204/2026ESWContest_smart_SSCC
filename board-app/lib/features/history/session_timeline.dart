import 'package:flutter/material.dart';

import '../../models/types.dart';
import '../../theme/theme.dart';
import '../../theme/tokens.dart';
import '../../util/format.dart';

Color _dot(String type, HvColors c) => switch (type) {
      'cooking_started' || 'user_returned' || 'overheat_cleared' => c.ok,
      'absence_detected' => c.caution,
      'auto_power_reduced' => c.warn,
      'auto_power_off' || 'overheat_detected' => c.danger,
      _ => c.ink3,
    };

/// 한 번의 조리 흐름 (정상 조리 → 이탈 → 자동 저감 → 복귀 → 종료). max 면 마지막 몇 개만
class SessionTimeline extends StatelessWidget {
  const SessionTimeline({super.key, required this.session, this.max, this.big = false});
  final CookingSession session;
  final int? max;
  final bool big;

  @override
  Widget build(BuildContext context) {
    final c = context.hv;
    final all = session.timeline;
    final entries = max != null && all.length > max! ? all.sublist(all.length - max!) : all;
    if (entries.isEmpty) return Text('아직 기록이 없어요', style: ts(14, color: c.ink3));
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      mainAxisSize: MainAxisSize.min,
      children: [
        for (var i = 0; i < entries.length; i++)
          IntrinsicHeight(
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                Padding(
                  padding: const EdgeInsets.only(top: 6),
                  child: Column(
                    children: [
                      Container(width: 10, height: 10, decoration: BoxDecoration(color: _dot(entries[i].type, c), shape: BoxShape.circle)),
                      if (i < entries.length - 1)
                        Expanded(child: Container(width: 1, margin: const EdgeInsets.symmetric(vertical: 4), color: c.line)),
                    ],
                  ),
                ),
                const SizedBox(width: 12),
                Expanded(
                  child: Padding(
                    padding: EdgeInsets.only(bottom: big ? 16 : 12),
                    child: Row(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        SizedBox(
                          width: big ? 56 : 48,
                          child: Text(formatTime(entries[i].at), style: ts(big ? 16 : 13, color: c.ink3, tabular: true)),
                        ),
                        const SizedBox(width: 12),
                        Expanded(child: Text(entries[i].summary, style: ts(big ? 18 : 14, color: c.ink, height: 1.4))),
                      ],
                    ),
                  ),
                ),
              ],
            ),
          ),
      ],
    );
  }
}
