import 'dart:async';
import 'dart:math' as math;

import 'package:flutter/widgets.dart';

import '../config.dart';

/// 디자인 기준 화면 (월패드 1280×720)
const designWidth = 1280.0;
const designHeight = 720.0;

/// 화면 크기 맞춤.
/// - 1280×720 이상이면 그대로 배치한다 (넓어지면 칸이 넓어진다)
/// - 그보다 작으면 배치를 깨지 않고 화면 전체를 비율대로 줄인다 (예: 1024×600 → 0.8배, 1280×750 배치)
/// - CANVAS_SCALE 을 주면 그 배율로 키운다 (예: 1920×1080 모니터에 1.5 → 1280×720 배치를 1.5배)
class ScaledCanvas extends StatelessWidget {
  const ScaledCanvas({super.key, required this.child, this.forcedScale});
  final Widget child;
  final double? forcedScale;

  static double scaleFor(Size size, double forced) {
    var s = forced > 0 ? forced : 1.0;
    if (size.width / s < designWidth || size.height / s < designHeight) {
      s = math.min(size.width / designWidth, size.height / designHeight);
    }
    return s <= 0 ? 1 : s;
  }

  @override
  Widget build(BuildContext context) {
    return LayoutBuilder(builder: (context, box) {
      final mq = MediaQuery.of(context);
      final w = box.maxWidth.isFinite ? box.maxWidth : mq.size.width;
      final h = box.maxHeight.isFinite ? box.maxHeight : mq.size.height;
      if (w <= 0 || h <= 0) return const SizedBox.shrink();
      final s = scaleFor(Size(w, h), forcedScale ?? canvasScale());
      final cw = w / s;
      final ch = h / s;
      return FittedBox(
        fit: BoxFit.contain,
        alignment: Alignment.topLeft,
        child: SizedBox(
          width: cw,
          height: ch,
          child: MediaQuery(
            data: mq.copyWith(size: Size(cw, ch), padding: EdgeInsets.zero, viewPadding: EdgeInsets.zero, viewInsets: EdgeInsets.zero),
            child: child,
          ),
        ),
      );
    });
  }
}

/// 주기적으로 다시 그린다 (시계 · 카운트다운 · "n초 전")
class NowBuilder extends StatefulWidget {
  const NowBuilder({super.key, required this.builder, this.interval = const Duration(seconds: 1)});
  final Widget Function(BuildContext context, DateTime now) builder;
  final Duration interval;

  @override
  State<NowBuilder> createState() => _NowBuilderState();
}

class _NowBuilderState extends State<NowBuilder> {
  late Timer _t;
  DateTime _now = DateTime.now();

  @override
  void initState() {
    super.initState();
    _t = Timer.periodic(widget.interval, (_) {
      if (mounted) setState(() => _now = DateTime.now());
    });
  }

  @override
  void dispose() {
    _t.cancel();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => widget.builder(context, _now);
}
