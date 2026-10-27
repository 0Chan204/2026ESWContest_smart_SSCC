// 추이 미니 그래프 · '온전히 들어가는 줄만' 목록 (React Sparkline · FitList)

import 'dart:math' as math;

import 'package:flutter/rendering.dart';
import 'package:flutter/widgets.dart';

/// 추이 미니 그래프. threshold 선(과열 기준)을 함께 그려 얼마나 가까운지 보이게 한다.
class Sparkline extends StatelessWidget {
  const Sparkline({
    super.key,
    required this.values,
    required this.max,
    required this.color,
    this.min = 20,
    this.threshold,
    this.thresholdColor,
  });

  final List<double> values;
  final double max;
  final double min;
  final double? threshold;
  final Color color;
  final Color? thresholdColor;

  @override
  Widget build(BuildContext context) => CustomPaint(
        painter: _SparkPainter(values, min, max, threshold, color, thresholdColor),
        size: Size.infinite,
      );
}

class _SparkPainter extends CustomPainter {
  _SparkPainter(this.values, this.min, this.max, this.threshold, this.color, this.thresholdColor);
  final List<double> values;
  final double min, max;
  final double? threshold;
  final Color color;
  final Color? thresholdColor;

  @override
  void paint(Canvas canvas, Size size) {
    if (size.width <= 0 || size.height <= 0) return;
    final w = size.width;
    final h = size.height;
    final span = math.max(1.0, max - min);
    final pts = values.length > 1 ? values : [values.isEmpty ? min : values.first, values.isEmpty ? min : values.first];
    final step = w / (pts.length - 1);
    double y(double v) => h - ((v.clamp(min, max) - min) / span) * (h - 6) - 3;
    final line = Path();
    for (var i = 0; i < pts.length; i++) {
      final p = Offset(i * step, y(pts[i]));
      i == 0 ? line.moveTo(p.dx, p.dy) : line.lineTo(p.dx, p.dy);
    }
    final area = Path.from(line)
      ..lineTo(w, h)
      ..lineTo(0, h)
      ..close();
    canvas.drawPath(area, Paint()..color = color.withValues(alpha: 0.12));
    final t = threshold;
    if (t != null) {
      final ty = y(t);
      final paint = Paint()
        ..color = (thresholdColor ?? color).withValues(alpha: 0.7)
        ..strokeWidth = 1;
      for (double x = 0; x < w; x += 8) {
        canvas.drawLine(Offset(x, ty), Offset(math.min(x + 4, w), ty), paint);
      }
    }
    canvas.drawPath(
      line,
      Paint()
        ..color = color
        ..style = PaintingStyle.stroke
        ..strokeWidth = 2
        ..strokeJoin = StrokeJoin.round,
    );
  }

  @override
  bool shouldRepaint(_SparkPainter old) =>
      old.values != values || old.color != color || old.max != max || old.min != min || old.threshold != threshold;
}

/// 높이가 정해진 칸에 '온전히 들어가는 줄'만 보여주는 세로 목록.
/// 마지막 줄이 반쯤 잘려 보이지 않게, 넘치는 줄은 그리지 않는다 (누를 수도 없다).
/// 높이 제한이 없으면 모두 보인다.
class FitColumn extends MultiChildRenderObjectWidget {
  const FitColumn({super.key, required super.children});

  @override
  RenderObject createRenderObject(BuildContext context) => RenderFitColumn();
}

class FitColumnParentData extends ContainerBoxParentData<RenderBox> {
  bool visible = true;
}

class RenderFitColumn extends RenderBox
    with ContainerRenderObjectMixin<RenderBox, FitColumnParentData>, RenderBoxContainerDefaultsMixin<RenderBox, FitColumnParentData> {
  /// 마지막 배치에서 보인 줄 수 (테스트용)
  int visibleCount = 0;

  @override
  void setupParentData(RenderBox child) {
    if (child.parentData is! FitColumnParentData) child.parentData = FitColumnParentData();
  }

  Size _layout(BoxConstraints constraints, {required bool dry}) {
    final w = constraints.maxWidth.isFinite ? constraints.maxWidth : 0.0;
    final maxH = constraints.maxHeight;
    var y = 0.0;
    var visibleBottom = 0.0;
    var overflowed = false;
    var count = 0;
    var child = firstChild;
    while (child != null) {
      final pd = child.parentData! as FitColumnParentData;
      final cc = BoxConstraints(minWidth: w, maxWidth: w);
      final s = dry ? child.getDryLayout(cc) : (child..layout(cc, parentUsesSize: true)).size;
      final bottom = y + s.height;
      final fits = !overflowed && bottom <= maxH + 0.5;
      if (!dry) {
        pd.offset = Offset(0, y);
        pd.visible = fits;
      }
      if (fits) {
        visibleBottom = bottom;
        count++;
      } else {
        overflowed = true;
      }
      y = bottom;
      child = pd.nextSibling;
    }
    if (!dry) visibleCount = count;
    return constraints.constrain(Size(w, maxH.isFinite ? visibleBottom : y));
  }

  @override
  void performLayout() => size = _layout(constraints, dry: false);

  @override
  Size computeDryLayout(BoxConstraints constraints) => _layout(constraints, dry: true);

  @override
  void paint(PaintingContext context, Offset offset) {
    var child = firstChild;
    while (child != null) {
      final pd = child.parentData! as FitColumnParentData;
      if (pd.visible) context.paintChild(child, offset + pd.offset);
      child = pd.nextSibling;
    }
  }

  @override
  bool hitTestChildren(BoxHitTestResult result, {required Offset position}) {
    var child = lastChild;
    while (child != null) {
      final pd = child.parentData! as FitColumnParentData;
      if (pd.visible) {
        final hit = result.addWithPaintOffset(
          offset: pd.offset,
          position: position,
          hitTest: (r, transformed) => child!.hitTest(r, position: transformed),
        );
        if (hit) return true;
      }
      child = pd.previousSibling;
    }
    return false;
  }

  @override
  void visitChildrenForSemantics(RenderObjectVisitor visitor) {
    var child = firstChild;
    while (child != null) {
      final pd = child.parentData! as FitColumnParentData;
      if (pd.visible) visitor(child);
      child = pd.nextSibling;
    }
  }
}
