import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../store/preferences.dart';
import 'tokens.dart';

const fontFamily = 'Pretendard';

ThemeData buildTheme(HvColors c) {
  final base = c.dark ? ThemeData.dark(useMaterial3: true) : ThemeData.light(useMaterial3: true);
  return base.copyWith(
    scaffoldBackgroundColor: c.canvas,
    canvasColor: c.canvas,
    textTheme: base.textTheme.apply(fontFamily: fontFamily, bodyColor: c.ink, displayColor: c.ink),
    primaryTextTheme: base.primaryTextTheme.apply(fontFamily: fontFamily),
    colorScheme: base.colorScheme.copyWith(primary: c.brand, surface: c.surface, onSurface: c.ink, error: c.danger),
    splashFactory: NoSplash.splashFactory,
    highlightColor: Colors.transparent,
    hoverColor: Colors.transparent,
    splashColor: Colors.transparent,
    extensions: [c],
  );
}

extension HvContext on BuildContext {
  HvColors get hv => Theme.of(this).extension<HvColors>() ?? HvColors.light;

  /// 어르신 모드 (큰 글씨 · 간단한 화면)
  bool get elderly => select<Preferences, bool>((p) => p.elderly);
}

/// 글자 모양 한 줄 도우미. size 는 React 의 px 값 (1rem = 16px).
/// 어르신 모드 확대는 MediaQuery.textScaler 가 맡는다 (여백은 그대로).
TextStyle ts(
  double size, {
  FontWeight weight = FontWeight.w400,
  Color? color,
  double? height,
  double tracking = 0,
  bool tabular = false,
}) =>
    TextStyle(
      fontFamily: fontFamily,
      fontSize: size,
      fontWeight: weight,
      color: color,
      height: height ?? 1.3,
      letterSpacing: tracking == 0 ? null : tracking * size,
      fontFeatures: tabular ? const [FontFeature.tabularFigures()] : null,
      leadingDistribution: TextLeadingDistribution.even,
    );

const w200 = FontWeight.w200;
const w300 = FontWeight.w300;
const w400 = FontWeight.w400;
const w500 = FontWeight.w500;
const w600 = FontWeight.w600;
const w700 = FontWeight.w700;
