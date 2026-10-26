import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../store/toaster.dart';
import '../theme/theme.dart';
import 'icons.dart';

/// 오른쪽 아래 토스트 (React sonner 자리). 누르면 닫힌다.
class ToastHost extends StatelessWidget {
  const ToastHost({super.key});

  @override
  Widget build(BuildContext context) {
    final items = context.watch<Toaster>().items;
    if (items.isEmpty) return const SizedBox.shrink();
    final c = context.hv;
    return Positioned(
      right: 24,
      bottom: 24,
      child: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.end,
        children: [
          for (final t in items)
            Padding(
              key: ValueKey(t.id),
              padding: const EdgeInsets.only(top: 8),
              child: GestureDetector(
                onTap: () => context.read<Toaster>().dismiss(t.id),
                child: TweenAnimationBuilder<double>(
                  tween: Tween(begin: 0, end: 1),
                  duration: const Duration(milliseconds: 220),
                  curve: Curves.easeOutCubic,
                  builder: (context, v, child) => Opacity(opacity: v, child: Transform.translate(offset: Offset(0, 12 * (1 - v)), child: child)),
                  child: Container(
                    constraints: const BoxConstraints(maxWidth: 420, minHeight: 52),
                    padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
                    decoration: BoxDecoration(
                      color: c.dark ? c.raised : c.surface,
                      borderRadius: BorderRadius.circular(14),
                      boxShadow: c.shadowPop,
                      border: Border.all(color: c.line),
                    ),
                    child: Row(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        if (t.error) ...[Icon(Ic.alert, size: 18, color: c.danger), const SizedBox(width: 10)],
                        Flexible(child: Text(t.text, style: ts(15, weight: w500, color: c.ink, height: 1.4))),
                      ],
                    ),
                  ),
                ),
              ),
            ),
        ],
      ),
    );
  }
}
