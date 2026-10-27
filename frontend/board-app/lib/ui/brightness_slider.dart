import 'dart:async';

import 'package:flutter/material.dart';

import '../theme/theme.dart';
import '../util/device_text.dart';
import 'icons.dart';

/// 밝기 슬라이더 (홈 앱 · 제어 센터의 알약 모양, React BrightnessSlider).
/// - 좌우로 끌면 밝기를 바꾸고, 손을 떼면 한 번만 보낸다
/// - 짧게 누르면 켜고 끈다
/// - steps 가 있으면 그 단계로만 멈춘다 (백엔드 전등: 끔 · 절전 20% · 100%)
/// - 보낸 값은 기기 상태가 바뀌거나 5초가 지날 때까지 먼저 보여준다 (그 뒤엔 실제 상태)
class BrightnessSlider extends StatefulWidget {
  const BrightnessSlider({
    super.key,
    required this.value,
    required this.onCommit,
    required this.onToggle,
    this.steps,
    this.savingLevel,
    this.name,
    this.disabled = false,
    this.large = false,
  });

  /// 지금 밝기 0~100 (0 = 꺼짐)
  final int value;
  final List<int>? steps;
  final int? savingLevel;
  final ValueChanged<int> onCommit;
  final VoidCallback onToggle;
  final String? name;
  final bool disabled;
  final bool large;

  @override
  State<BrightnessSlider> createState() => _BrightnessSliderState();
}

const _pendingFor = Duration(seconds: 5);

class _BrightnessSliderState extends State<BrightnessSlider> {
  int? _draft;
  ({int v, int base})? _pending;
  Timer? _pendingTimer;
  double _dragStartX = 0;
  int _dragStartValue = 0;

  int get _shown {
    if (_draft != null) return _draft!;
    final p = _pending;
    if (p != null && p.base == widget.value) return p.v;
    return widget.value;
  }

  @override
  void dispose() {
    _pendingTimer?.cancel();
    super.dispose();
  }

  void _commit(int v) {
    setState(() => _draft = null);
    if (v == widget.value) {
      setState(() => _pending = null);
      return;
    }
    setState(() => _pending = (v: v, base: widget.value));
    _pendingTimer?.cancel();
    _pendingTimer = Timer(_pendingFor, () {
      if (mounted) setState(() => _pending = null);
    });
    widget.onCommit(v);
  }

  @override
  Widget build(BuildContext context) {
    final c = context.hv;
    final shown = _shown;
    final lit = shown > 0;
    final text = brightnessLabel(shown, widget.savingLevel);
    final ticks = (widget.steps ?? const <int>[]).where((s) => s > 0 && s < 100).toList();
    final lg = widget.large;

    return LayoutBuilder(builder: (context, box) {
      final width = box.maxWidth.isFinite && box.maxWidth > 0 ? box.maxWidth : 1.0;
      return Semantics(
        container: true,
        slider: true,
        value: text,
        label: widget.name,
        enabled: !widget.disabled,
        child: MouseRegion(
          cursor: widget.disabled ? MouseCursor.defer : SystemMouseCursors.click,
          child: GestureDetector(
            behavior: HitTestBehavior.opaque,
            onTap: widget.disabled
                ? null
                : () {
                    setState(() {
                      _draft = null;
                      _pending = null;
                    });
                    widget.onToggle();
                  },
            onHorizontalDragStart: widget.disabled
                ? null
                : (d) {
                    _dragStartX = d.localPosition.dx;
                    _dragStartValue = shown;
                  },
            onHorizontalDragUpdate: widget.disabled
                ? null
                : (d) {
                    final dx = d.localPosition.dx - _dragStartX;
                    setState(() => _draft = snapBrightness(_dragStartValue + dx / width * 100, widget.steps));
                  },
            onHorizontalDragEnd: widget.disabled ? null : (_) => _commit(_draft ?? shown),
            onHorizontalDragCancel: widget.disabled ? null : () => setState(() => _draft = null),
            child: Opacity(
              opacity: widget.disabled ? 0.4 : 1,
              child: Container(
                height: lg ? 64 : 56,
                clipBehavior: Clip.antiAlias,
                decoration: BoxDecoration(color: c.fill, borderRadius: BorderRadius.circular(18)),
                child: Stack(
                  children: [
                    // 채움: 밝기만큼 따뜻한 색
                    AnimatedPositioned(
                      duration: _draft == null ? const Duration(milliseconds: 300) : Duration.zero,
                      curve: Curves.easeOut,
                      left: 0,
                      top: 0,
                      bottom: 0,
                      width: width * shown / 100,
                      child: ColoredBox(color: c.glyphLight.withValues(alpha: 0.3)),
                    ),
                    for (final t in ticks)
                      Positioned(
                        left: width * t / 100 - 2,
                        bottom: 8,
                        child: Container(
                          width: 4,
                          height: 4,
                          decoration: BoxDecoration(color: c.ink3.withValues(alpha: 0.5), shape: BoxShape.circle),
                        ),
                      ),
                    Positioned.fill(
                      child: Row(
                        children: [
                          const SizedBox(width: 16),
                          Icon(Ic.light, size: lg ? 28 : 24, color: lit ? c.glyphLight : c.ink3),
                          if (widget.name != null) ...[
                            const SizedBox(width: 12),
                            Expanded(
                              child: Text(widget.name!,
                                  style: ts(lg ? 18 : 16, weight: w600, color: c.ink), maxLines: 1, overflow: TextOverflow.ellipsis),
                            ),
                          ] else
                            const Spacer(),
                          const SizedBox(width: 12),
                          Text(text, style: ts(lg ? 18 : 15, weight: w600, color: lit ? c.ink : c.ink2, tabular: true)),
                          const SizedBox(width: 16),
                        ],
                      ),
                    ),
                  ],
                ),
              ),
            ),
          ),
        ),
      );
    });
  }
}
