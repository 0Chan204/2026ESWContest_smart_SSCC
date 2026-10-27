// 기본 부품 (React src/components/ui): 누름 반응 · 카드 · 묶음 목록 · 세그먼트 · 스위치 · 버튼 · 색 사각 아이콘.
// 보드는 터치 · 마우스만 있으므로 누르는 범위는 48×48 이상으로 둔다.

import 'package:flutter/material.dart';

import '../theme/theme.dart';
import '../theme/tokens.dart';
import 'icons.dart';

/// 누르면 살짝 흐려지고 작아지는 반응 (iOS 기본 버튼, React .press)
class Pressable extends StatefulWidget {
  const Pressable({super.key, required this.child, this.onTap, this.semanticLabel, this.behavior = HitTestBehavior.opaque});

  final Widget child;
  final VoidCallback? onTap;
  final String? semanticLabel;
  final HitTestBehavior behavior;

  @override
  State<Pressable> createState() => _PressableState();
}

class _PressableState extends State<Pressable> {
  bool _down = false;

  void _set(bool v) {
    if (_down != v && mounted) setState(() => _down = v);
  }

  @override
  Widget build(BuildContext context) {
    final enabled = widget.onTap != null;
    return Semantics(
      container: true,
      button: true,
      enabled: enabled,
      label: widget.semanticLabel,
      child: MouseRegion(
        cursor: enabled ? SystemMouseCursors.click : MouseCursor.defer,
        child: GestureDetector(
          behavior: widget.behavior,
          onTapDown: enabled ? (_) => _set(true) : null,
          onTapUp: enabled ? (_) => _set(false) : null,
          onTapCancel: enabled ? () => _set(false) : null,
          onTap: widget.onTap,
          child: AnimatedOpacity(
            opacity: _down ? 0.72 : 1,
            duration: const Duration(milliseconds: 140),
            child: AnimatedScale(scale: _down ? 0.985 : 1, duration: const Duration(milliseconds: 140), child: widget.child),
          ),
        ),
      ),
    );
  }
}

/// 흰(다크: 짙은 회색) 면. 테두리 없이 바탕과의 대비로 구분 (React Card, rounded-2xl = 18)
class HvCard extends StatelessWidget {
  const HvCard({super.key, required this.child, this.color, this.padding = const EdgeInsets.all(24), this.radius = 18});

  final Widget child;
  final Color? color;
  final EdgeInsetsGeometry padding;
  final double radius;

  @override
  Widget build(BuildContext context) => Container(
        padding: padding,
        decoration: BoxDecoration(color: color ?? context.hv.surface, borderRadius: BorderRadius.circular(radius)),
        child: child,
      );
}

/// 화면 안 구역 제목 (iOS 굵은 섹션 제목)
class SectionTitle extends StatelessWidget {
  const SectionTitle({super.key, required this.title, this.count, this.action});
  final String title;
  final String? count;
  final Widget? action;

  @override
  Widget build(BuildContext context) {
    final c = context.hv;
    return Padding(
      padding: const EdgeInsets.only(bottom: 10),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.end,
        children: [
          Expanded(
            child: Text.rich(
              TextSpan(children: [
                TextSpan(text: title),
                if (count != null) TextSpan(text: ' $count', style: ts(20, weight: w400, color: c.ink3)),
              ]),
              style: ts(20, weight: w700, color: c.ink, tracking: -0.01),
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
            ),
          ),
          if (action != null) action!,
        ],
      ),
    );
  }
}

/// iOS 설정 앱의 색깔 사각 아이콘
enum SymColor { blue, green, gray, red, orange, indigo }

class SymbolIcon extends StatelessWidget {
  const SymbolIcon({super.key, required this.icon, required this.color});
  final IconData icon;
  final SymColor color;

  @override
  Widget build(BuildContext context) {
    final bg = switch (color) {
      SymColor.blue => HvColors.symBlue,
      SymColor.green => HvColors.symGreen,
      SymColor.gray => HvColors.symGray,
      SymColor.red => HvColors.symRed,
      SymColor.orange => HvColors.symOrange,
      SymColor.indigo => HvColors.symIndigo,
    };
    return Container(
      width: 30,
      height: 30,
      decoration: BoxDecoration(color: bg, borderRadius: BorderRadius.circular(8)),
      alignment: Alignment.center,
      child: Icon(icon, size: 18, color: Colors.white),
    );
  }
}

// ── 묶음 목록 (iOS 설정 앱) ────────────────────────────────────────────────
class _RowPosition extends InheritedWidget {
  const _RowPosition({required this.first, required super.child});
  final bool first;
  static bool isFirst(BuildContext context) => context.dependOnInheritedWidgetOfExactType<_RowPosition>()?.first ?? true;
  @override
  bool updateShouldNotify(_RowPosition old) => old.first != first;
}

/// 제목(작은 회색) · 둥근 칸 · 줄 사이 얇은 구분선 · 아래 설명
class ListGroup extends StatelessWidget {
  const ListGroup({
    super.key,
    this.title,
    this.footer,
    this.action,
    required this.children,
    this.bodyPadding,
    this.expand = false,
  });

  final String? title;
  final String? footer;
  final Widget? action;
  final List<Widget> children;
  final EdgeInsetsGeometry? bodyPadding;

  /// 남은 높이를 채운다 (부모가 높이를 정해 줄 때)
  final bool expand;

  @override
  Widget build(BuildContext context) {
    final c = context.hv;
    final body = Container(
      clipBehavior: Clip.antiAlias,
      padding: bodyPadding,
      decoration: BoxDecoration(color: c.surface, borderRadius: BorderRadius.circular(12)),
      child: Column(
        mainAxisSize: expand ? MainAxisSize.max : MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          for (var i = 0; i < children.length; i++) _RowPosition(first: i == 0, child: children[i]),
        ],
      ),
    );
    return Column(
      mainAxisSize: expand ? MainAxisSize.max : MainAxisSize.min,
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        if (title != null || action != null)
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 0, 16, 6),
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.end,
              children: [
                Expanded(
                    child: Text(title ?? '',
                        style: ts(13, weight: w500, color: c.ink3), maxLines: 1, overflow: TextOverflow.ellipsis)),
                if (action != null) action!,
              ],
            ),
          ),
        if (expand) Expanded(child: body) else body,
        if (footer != null)
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 6, 16, 0),
            child: Text(footer!, style: ts(13, color: c.ink3, height: 1.4)),
          ),
      ],
    );
  }
}

/// 위쪽 구분선 (목록의 두 번째 줄부터, 아이콘 뒤에서 시작)
class RowSeparator extends StatelessWidget {
  const RowSeparator({super.key, required this.child});
  final Widget child;
  @override
  Widget build(BuildContext context) {
    final first = _RowPosition.isFirst(context);
    return DecoratedBox(
      decoration: BoxDecoration(border: first ? null : Border(top: BorderSide(color: context.hv.line))),
      child: child,
    );
  }
}

/// 목록 한 줄. onTap 이 있으면 버튼이 된다.
class ListRow extends StatelessWidget {
  const ListRow({
    super.key,
    required this.title,
    this.leading,
    this.subtitle,
    this.value,
    this.valueWidget,
    this.trailing,
    this.chevron = false,
    this.onTap,
    this.big = false,
    this.titleWeight = w400,
    this.wrap = false,
  });

  final String title;
  final Widget? leading;
  final String? subtitle;
  final String? value;
  final Widget? valueWidget;
  final Widget? trailing;
  final bool chevron;
  final VoidCallback? onTap;
  final bool big;
  final FontWeight titleWeight;
  final bool wrap;

  @override
  Widget build(BuildContext context) {
    final c = context.hv;
    final row = Padding(
      padding: const EdgeInsets.only(left: 16),
      child: Row(
        children: [
          if (leading != null) ...[leading!, const SizedBox(width: 12)],
          Expanded(
            child: RowSeparator(
              child: ConstrainedBox(
                constraints: BoxConstraints(minHeight: big ? 64 : 52),
                child: Padding(
                  padding: EdgeInsets.fromLTRB(0, big ? 10 : 8, 16, big ? 10 : 8),
                  child: Row(
                    children: [
                      Expanded(
                        child: Column(
                          mainAxisSize: MainAxisSize.min,
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Text(title,
                                style: ts(big ? 20 : 16, weight: titleWeight, color: c.ink),
                                maxLines: 1,
                                overflow: TextOverflow.ellipsis),
                            if (subtitle != null)
                              Text(subtitle!,
                                  style: ts(big ? 16 : 13, color: c.ink2, height: wrap ? 1.35 : 1.3),
                                  maxLines: wrap ? 3 : 1,
                                  overflow: TextOverflow.ellipsis),
                          ],
                        ),
                      ),
                      if (value != null) ...[
                        const SizedBox(width: 12),
                        Text(value!, style: ts(big ? 17 : 15, color: c.ink2, tabular: true)),
                      ],
                      if (valueWidget != null) ...[const SizedBox(width: 12), valueWidget!],
                      if (trailing != null) ...[const SizedBox(width: 12), trailing!],
                      if (chevron) ...[const SizedBox(width: 8), Icon(Ic.chevronRight, size: 16, color: c.ink3)],
                    ],
                  ),
                ),
              ),
            ),
          ),
        ],
      ),
    );
    return onTap == null ? row : Pressable(onTap: onTap, child: row);
  }
}

// ── 세그먼트 · 스위치 · 버튼 ─────────────────────────────────────────────────
enum SegSize { md, touch, lg }

class SegOption<T> {
  const SegOption(this.value, this.label);
  final T value;
  final String label;
}

/// iOS 세그먼트 컨트롤. 같은 자리에서 보기를 바꿀 때
class Segmented<T> extends StatelessWidget {
  const Segmented({super.key, required this.value, required this.options, required this.onChanged, this.size = SegSize.md});

  final T value;
  final List<SegOption<T>> options;
  final ValueChanged<T> onChanged;
  final SegSize size;

  @override
  Widget build(BuildContext context) {
    final c = context.hv;
    final h = switch (size) { SegSize.md => 42.0, SegSize.touch => 44.0, SegSize.lg => 48.0 };
    final fs = switch (size) { SegSize.md => 14.0, SegSize.touch => 15.0, SegSize.lg => 17.0 };
    return Container(
      padding: const EdgeInsets.all(3),
      decoration: BoxDecoration(color: c.fill, borderRadius: BorderRadius.circular(10)),
      child: Row(
        children: [
          for (final o in options)
            Expanded(
              child: Semantics(
                container: true,
                selected: o.value == value,
                button: true,
                child: MouseRegion(
                  cursor: SystemMouseCursors.click,
                  child: GestureDetector(
                    behavior: HitTestBehavior.opaque,
                    onTap: () => onChanged(o.value),
                    child: AnimatedContainer(
                      duration: const Duration(milliseconds: 160),
                      constraints: BoxConstraints(minHeight: h),
                      alignment: Alignment.center,
                      padding: const EdgeInsets.symmetric(horizontal: 6),
                      decoration: BoxDecoration(
                        color: o.value == value ? c.thumb : Colors.transparent,
                        borderRadius: BorderRadius.circular(8),
                        boxShadow: o.value == value ? c.shadowThumb : null,
                      ),
                      child: Text(o.label,
                          style: ts(fs, weight: w600, color: c.ink),
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                          textAlign: TextAlign.center),
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

/// iOS 스위치 (켜지면 초록). 보이는 크기는 iOS 그대로, 누르는 범위는 48 이상
class HvToggle extends StatelessWidget {
  const HvToggle({super.key, required this.checked, required this.onChanged, this.disabled = false, this.large = false, this.label});

  final bool checked;
  final ValueChanged<bool> onChanged;
  final bool disabled;
  final bool large;
  final String? label;

  @override
  Widget build(BuildContext context) {
    final c = context.hv;
    final w = large ? 64.0 : 51.0;
    final h = large ? 38.0 : 31.0;
    final k = large ? 34.0 : 27.0;
    return Semantics(
      container: true,
      toggled: checked,
      enabled: !disabled,
      label: label,
      child: MouseRegion(
        cursor: disabled ? MouseCursor.defer : SystemMouseCursors.click,
        child: GestureDetector(
          behavior: HitTestBehavior.opaque,
          onTap: disabled ? null : () => onChanged(!checked),
          child: SizedBox(
            width: w + 14,
            height: h + 18 < 48 ? 48 : h + 18,
            child: Center(
              child: Opacity(
                opacity: disabled ? 0.4 : 1,
                child: AnimatedContainer(
                  duration: const Duration(milliseconds: 200),
                  width: w,
                  height: h,
                  padding: const EdgeInsets.all(2),
                  decoration: BoxDecoration(color: checked ? c.switchOn : c.track, borderRadius: BorderRadius.circular(h)),
                  child: AnimatedAlign(
                    duration: const Duration(milliseconds: 200),
                    curve: Curves.easeOut,
                    alignment: checked ? Alignment.centerRight : Alignment.centerLeft,
                    child: Container(
                      width: k,
                      height: k,
                      decoration: const BoxDecoration(
                        color: Colors.white,
                        shape: BoxShape.circle,
                        boxShadow: [
                          BoxShadow(color: Color.fromRGBO(0, 0, 0, 0.15), offset: Offset(0, 3), blurRadius: 8),
                          BoxShadow(color: Color.fromRGBO(0, 0, 0, 0.16), offset: Offset(0, 1), blurRadius: 1),
                        ],
                      ),
                    ),
                  ),
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }
}

enum BtnVariant { primary, secondary, plain, danger, ghost, quiet }

enum BtnSize { sm, md, lg, xl }

/// iOS 버튼: 채움(파랑) · 회색 · 흰색 · 위험(빨강) · 글자만
class HvButton extends StatelessWidget {
  const HvButton({
    super.key,
    required this.label,
    this.onPressed,
    this.variant = BtnVariant.secondary,
    this.size = BtnSize.md,
    this.icon,
    this.expand = false,
    this.busy = false,
  });

  final String label;
  final VoidCallback? onPressed;
  final BtnVariant variant;
  final BtnSize size;
  final IconData? icon;
  final bool expand;
  final bool busy;

  @override
  Widget build(BuildContext context) {
    final c = context.hv;
    final (Color bg, Color fg) = switch (variant) {
      BtnVariant.primary => (c.brand, Colors.white),
      BtnVariant.secondary => (c.fill, c.ink),
      BtnVariant.plain => (c.surface, c.ink),
      BtnVariant.danger => (c.dangerFill, Colors.white),
      BtnVariant.ghost => (Colors.transparent, c.brandInk),
      BtnVariant.quiet => (Colors.transparent, c.ink2),
    };
    final (double minH, double fs, double r, double px) = switch (size) {
      BtnSize.sm => (44.0, 14.0, 10.0, 14.0),
      BtnSize.md => (48.0, 16.0, 12.0, 16.0),
      BtnSize.lg => (50.0, 17.0, 14.0, 20.0),
      BtnSize.xl => (60.0, 20.0, 16.0, 24.0),
    };
    final disabled = onPressed == null;
    final content = Row(
      mainAxisSize: expand ? MainAxisSize.max : MainAxisSize.min,
      mainAxisAlignment: MainAxisAlignment.center,
      children: [
        if (busy)
          Padding(padding: const EdgeInsets.only(right: 8), child: SpinningIcon(icon: Ic.refresh, size: 20, color: fg))
        else if (icon != null)
          Padding(padding: const EdgeInsets.only(right: 8), child: Icon(icon, size: fs + 2, color: fg)),
        Flexible(child: Text(label, style: ts(fs, weight: w600, color: fg), maxLines: 1, overflow: TextOverflow.ellipsis)),
      ],
    );
    return Opacity(
      opacity: disabled ? 0.4 : 1,
      child: Pressable(
        onTap: onPressed,
        child: Container(
          constraints: BoxConstraints(minHeight: minH),
          padding: EdgeInsets.symmetric(horizontal: px),
          decoration: BoxDecoration(color: bg, borderRadius: BorderRadius.circular(r)),
          alignment: expand ? Alignment.center : null,
          child: content,
        ),
      ),
    );
  }
}

/// 천천히 도는 아이콘 (확인 중 · 연결 중)
class SpinningIcon extends StatefulWidget {
  const SpinningIcon({super.key, required this.icon, required this.size, required this.color, this.spinning = true});
  final IconData icon;
  final double size;
  final Color color;
  final bool spinning;
  @override
  State<SpinningIcon> createState() => _SpinningIconState();
}

class _SpinningIconState extends State<SpinningIcon> with SingleTickerProviderStateMixin {
  late final AnimationController _c = AnimationController(vsync: this, duration: const Duration(milliseconds: 900));

  @override
  void initState() {
    super.initState();
    if (widget.spinning) _c.repeat();
  }

  @override
  void didUpdateWidget(SpinningIcon old) {
    super.didUpdateWidget(old);
    if (widget.spinning && !_c.isAnimating) _c.repeat();
    if (!widget.spinning && _c.isAnimating) _c.stop();
  }

  @override
  void dispose() {
    _c.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) =>
      RotationTransition(turns: _c, child: Icon(widget.icon, size: widget.size, color: widget.color));
}

/// 위험 상태에서만 쓰는 느린 점멸 (React .soft-pulse)
class SoftPulse extends StatefulWidget {
  const SoftPulse({super.key, required this.child, this.active = true});
  final Widget child;
  final bool active;
  @override
  State<SoftPulse> createState() => _SoftPulseState();
}

class _SoftPulseState extends State<SoftPulse> with SingleTickerProviderStateMixin {
  // 처음부터 만든다 (지연 생성이면 dispose 에서 처음 만들어져 오류가 난다)
  late final AnimationController _c;
  late final Animation<double> _a;

  @override
  void initState() {
    super.initState();
    _c = AnimationController(vsync: this, duration: const Duration(milliseconds: 1600));
    _a = TweenSequence([
      TweenSequenceItem(tween: Tween(begin: 1.0, end: 0.45), weight: 1),
      TweenSequenceItem(tween: Tween(begin: 0.45, end: 1.0), weight: 1),
    ]).animate(CurvedAnimation(parent: _c, curve: Curves.easeInOut));
    if (widget.active) _c.repeat();
  }

  @override
  void didUpdateWidget(SoftPulse old) {
    super.didUpdateWidget(old);
    if (widget.active && !_c.isAnimating) _c.repeat();
    if (!widget.active && _c.isAnimating) {
      _c.stop();
      _c.value = 0;
    }
  }

  @override
  void dispose() {
    _c.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => widget.active ? FadeTransition(opacity: _a, child: widget.child) : widget.child;
}

/// 현재 위치 표시 — 은은하게 퍼지는 원 (React .locate)
class LocateDot extends StatefulWidget {
  const LocateDot({super.key, required this.size, required this.color, this.child, this.ringColor});
  final double size;
  final Color color;
  final Color? ringColor;
  final Widget? child;
  @override
  State<LocateDot> createState() => _LocateDotState();
}

class _LocateDotState extends State<LocateDot> with SingleTickerProviderStateMixin {
  late final AnimationController _c = AnimationController(vsync: this, duration: const Duration(milliseconds: 2200))..repeat();

  @override
  void dispose() {
    _c.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      width: widget.size,
      height: widget.size,
      child: Stack(
        clipBehavior: Clip.none,
        alignment: Alignment.center,
        children: [
          AnimatedBuilder(
            animation: _c,
            builder: (context, _) {
              final t = Curves.easeOut.transform(_c.value);
              return Transform.scale(
                scale: 1 + 1.6 * t,
                child: Container(
                  width: widget.size,
                  height: widget.size,
                  decoration: BoxDecoration(color: widget.color.withValues(alpha: 0.5 * (1 - t)), shape: BoxShape.circle),
                ),
              );
            },
          ),
          Container(
            width: widget.size,
            height: widget.size,
            decoration: BoxDecoration(
              color: widget.color,
              shape: BoxShape.circle,
              border: widget.ringColor != null ? Border.all(color: widget.ringColor!, width: 3) : null,
            ),
            alignment: Alignment.center,
            child: widget.child,
          ),
        ],
      ),
    );
  }
}
