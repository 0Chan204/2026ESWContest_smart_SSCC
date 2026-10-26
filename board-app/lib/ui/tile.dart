import 'package:flutter/material.dart';

import '../theme/theme.dart';
import 'icons.dart';
import 'widgets.dart';

enum TileTone { danger, warn, muted }

/// 기기 · 상태 타일 (iPad '홈' 앱 방식, React Tile).
///  - on: 밝게 반전된 타일 + 색 아이콘 / off: 바탕보다 어두운 타일 + 흐린 아이콘 · 글자
///  - danger · warn: 연한 상태색 바탕
class Tile extends StatelessWidget {
  const Tile({
    super.key,
    required this.icon,
    required this.name,
    required this.state,
    this.glyph,
    this.on = false,
    this.tone,
    this.value,
    this.onPress,
    this.onMore,
    this.big = false,
  });

  final IconData icon;
  final String name;
  final String state;

  /// 켜졌을 때 아이콘 색
  final Color? glyph;
  final bool on;
  final TileTone? tone;

  /// 오른쪽 위에 크게 보일 값 (예: 98°)
  final String? value;
  final VoidCallback? onPress;

  /// 오른쪽 아래 '더 보기' (타일을 눌러 켜고 끄는 기기의 상세)
  final VoidCallback? onMore;
  final bool big;

  @override
  Widget build(BuildContext context) {
    final c = context.hv;
    final bg = tone == TileTone.danger
        ? c.dangerSoft
        : tone == TileTone.warn
            ? c.warnSoft
            : on
                ? c.tileOn
                : c.tileOff;
    final off = !on && (tone == null || tone == TileTone.muted);
    final iconColor = tone == TileTone.danger
        ? c.danger
        : tone == TileTone.warn
            ? c.warn
            : on
                ? (glyph ?? c.brandInk)
                : c.ink3.withValues(alpha: 0.7);
    final nameColor = off ? c.ink2 : (tone != null ? c.ink : c.tileOnInk);
    final stateColor = tone == TileTone.danger
        ? c.danger
        : tone == TileTone.warn
            ? c.warn
            : on
                ? c.tileOnInk2
                : c.ink2;
    final stateWeight = (tone == TileTone.danger || tone == TileTone.warn) ? w600 : w400;
    final valueColor = tone == TileTone.danger ? c.danger : (on ? c.tileOnInk : c.ink);

    final body = Container(
      padding: EdgeInsets.all(big ? 20 : 16),
      decoration: BoxDecoration(
        color: bg,
        borderRadius: BorderRadius.circular(18),
        boxShadow: on && tone == null ? c.shadowTile : null,
        border: off ? Border.all(color: c.line.withValues(alpha: 0.7)) : null,
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        mainAxisAlignment: MainAxisAlignment.spaceBetween,
        children: [
          Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Icon(icon, size: big ? 36 : 28, color: iconColor),
              const SizedBox(width: 12),
              Expanded(
                child: value == null
                    ? const SizedBox.shrink()
                    : Align(
                        alignment: Alignment.topRight,
                        child: FittedBox(
                          fit: BoxFit.scaleDown,
                          alignment: Alignment.topRight,
                          child: Text(value!,
                              style: ts(big ? 52 : 40, weight: w300, color: valueColor, height: 1, tracking: -0.03, tabular: true)),
                        ),
                      ),
              ),
            ],
          ),
          Padding(
            padding: EdgeInsets.only(right: onMore != null ? 32 : 0, top: 8),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              mainAxisSize: MainAxisSize.min,
              children: [
                Text(name, style: ts(big ? 22 : 15, weight: w600, color: nameColor), maxLines: 1, overflow: TextOverflow.ellipsis),
                Text(state,
                    style: ts(big ? 18 : 13, weight: stateWeight, color: stateColor), maxLines: 1, overflow: TextOverflow.ellipsis),
              ],
            ),
          ),
        ],
      ),
    );

    return Stack(
      fit: StackFit.expand,
      children: [
        onPress != null ? Pressable(onTap: onPress, child: body) : body,
        if (onMore != null)
          Positioned(
            right: 4,
            bottom: 4,
            child: Pressable(
              onTap: onMore,
              semanticLabel: '$name 자세히',
              child: SizedBox(
                width: 48,
                height: 48,
                child: Icon(Ic.more, size: 20, color: on ? c.tileOnInk2 : c.ink3),
              ),
            ),
          ),
      ],
    );
  }
}
