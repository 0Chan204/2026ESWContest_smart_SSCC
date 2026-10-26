import 'package:flutter/material.dart';

import '../theme/theme.dart';
import 'icons.dart';
import 'widgets.dart';

enum SheetVariant { center, side }

/// 모달 시트 틀 (React Sheet). center = 가운데 대화상자, side = 오른쪽 상세 패널.
/// 닫기는 iOS 의 회색 원형 X (누르는 범위 48).
class SheetFrame extends StatelessWidget {
  const SheetFrame({
    super.key,
    required this.child,
    required this.onClose,
    this.title,
    this.subtitle,
    this.footer,
    this.variant = SheetVariant.center,
    this.width = 520,
    this.hideClose = false,
    this.scrollable = true,
  });

  final Widget child;
  final VoidCallback onClose;
  final String? title;
  final Widget? subtitle;
  final Widget? footer;
  final SheetVariant variant;
  final double width;
  final bool hideClose;

  /// 내용이 넘치면 시트 안에서 스크롤 (끄면 내용이 직접 높이를 맞춘다)
  final bool scrollable;

  @override
  Widget build(BuildContext context) {
    final c = context.hv;
    final side = variant == SheetVariant.side;
    final hasHeader = title != null || !hideClose;
    final header = hasHeader
        ? Padding(
            padding: const EdgeInsets.fromLTRB(24, 16, 12, 8),
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Expanded(
                  child: Padding(
                    padding: const EdgeInsets.only(top: 6),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        if (title != null)
                          Text(title!, style: ts(22, weight: w700, color: c.ink, height: 1.25, tracking: -0.01)),
                        if (subtitle != null)
                          Padding(
                            padding: const EdgeInsets.only(top: 4),
                            child: DefaultTextStyle(style: ts(14, color: c.ink2), child: subtitle!),
                          ),
                      ],
                    ),
                  ),
                ),
                if (!hideClose)
                  Pressable(
                    onTap: onClose,
                    semanticLabel: '닫기',
                    child: SizedBox(
                      width: 48,
                      height: 48,
                      child: Center(
                        child: Container(
                          width: 30,
                          height: 30,
                          decoration: BoxDecoration(color: c.fill, shape: BoxShape.circle),
                          child: Icon(Ic.x, size: 16, color: c.ink2),
                        ),
                      ),
                    ),
                  ),
              ],
            ),
          )
        : const SizedBox(height: 8);
    final body = Padding(padding: const EdgeInsets.fromLTRB(20, 0, 20, 20), child: child);

    return LayoutBuilder(builder: (context, box) {
      final maxW = (box.maxWidth - (side ? 24 : 48)).clamp(200.0, width);
      final panel = Container(
        width: maxW,
        decoration: BoxDecoration(color: c.canvas, borderRadius: BorderRadius.circular(22), boxShadow: c.shadowPop),
        clipBehavior: Clip.antiAlias,
        child: Material(
          type: MaterialType.transparency,
          child: Column(
            mainAxisSize: side ? MainAxisSize.max : MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              header,
              if (scrollable)
                Flexible(fit: side ? FlexFit.tight : FlexFit.loose, child: SingleChildScrollView(child: body))
              else
                Flexible(fit: side ? FlexFit.tight : FlexFit.loose, child: body),
              if (footer != null) Padding(padding: const EdgeInsets.fromLTRB(20, 4, 20, 20), child: footer),
            ],
          ),
        ),
      );
      return side
          ? Align(alignment: Alignment.centerRight, child: Padding(padding: const EdgeInsets.all(12), child: panel))
          : Center(
              child: Padding(
                padding: const EdgeInsets.all(24),
                child: ConstrainedBox(constraints: BoxConstraints(maxHeight: box.maxHeight - 48), child: panel),
              ),
            );
    });
  }
}

/// 시트를 띄운다 (Navigator 대화상자 경로 — 화면 축소 · 글자 배율이 그대로 적용된다)
Future<void> showSheet(BuildContext context, WidgetBuilder builder, {bool dismissible = true, SheetVariant variant = SheetVariant.center}) {
  final c = context.hv;
  return showGeneralDialog<void>(
    context: context,
    barrierDismissible: dismissible,
    barrierLabel: '닫기',
    barrierColor: c.scrim,
    transitionDuration: const Duration(milliseconds: 200),
    pageBuilder: (ctx, _, __) => builder(ctx),
    transitionBuilder: (ctx, anim, _, child) {
      final curved = CurvedAnimation(parent: anim, curve: Curves.easeOutCubic);
      final offset = variant == SheetVariant.side ? const Offset(0.06, 0) : const Offset(0, 0.03);
      return FadeTransition(
        opacity: curved,
        child: SlideTransition(position: Tween(begin: offset, end: Offset.zero).animate(curved), child: child),
      );
    },
  );
}

/// 스토어 상태로 열리는 시트(낙상 · 안전 조치)용 겹 — 화면 전체를 덮는 어두운 바탕 + 시트
class ModalLayer extends StatelessWidget {
  const ModalLayer({super.key, required this.child, this.onBarrierTap});
  final Widget child;
  final VoidCallback? onBarrierTap;

  @override
  Widget build(BuildContext context) {
    return Stack(
      children: [
        Positioned.fill(
          child: GestureDetector(behavior: HitTestBehavior.opaque, onTap: onBarrierTap, child: ColoredBox(color: context.hv.scrim)),
        ),
        Positioned.fill(child: child),
      ],
    );
  }
}
