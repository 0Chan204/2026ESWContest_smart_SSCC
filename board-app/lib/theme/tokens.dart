// 디자인 토큰 (React src/styles/index.css 와 같은 값 · docs/style-guide.md).
// 바탕 · 면은 순백 · 순흑 대신 웜 그레이. 상태색은 Apple 시스템 색 계열.

import 'package:flutter/material.dart';

import '../models/types.dart';

@immutable
class HvColors extends ThemeExtension<HvColors> {
  const HvColors({
    required this.dark,
    required this.canvas,
    required this.surface,
    required this.sunken,
    required this.raised,
    required this.line,
    required this.track,
    required this.fill,
    required this.thumb,
    required this.ink,
    required this.ink2,
    required this.ink3,
    required this.brand,
    required this.brandDark,
    required this.brandSoft,
    required this.brandInk,
    required this.switchOn,
    required this.ok,
    required this.okSoft,
    required this.caution,
    required this.cautionSoft,
    required this.warn,
    required this.warnSoft,
    required this.danger,
    required this.dangerSoft,
    required this.dangerFill,
    required this.mutedSoft,
    required this.tileOn,
    required this.tileOnInk,
    required this.tileOnInk2,
    required this.cardOn,
    required this.tileOff,
    required this.glyphLight,
    required this.glyphFan,
    required this.glyphWater,
    required this.glyphHeat,
    required this.glyphAir,
    required this.scrim,
    required this.shadowPop,
    required this.shadowTile,
    required this.shadowThumb,
  });

  final bool dark;
  final Color canvas, surface, sunken, raised, line, track, fill, thumb;
  final Color ink, ink2, ink3;
  final Color brand, brandDark, brandSoft, brandInk, switchOn;
  final Color ok, okSoft, caution, cautionSoft, warn, warnSoft, danger, dangerSoft, dangerFill, mutedSoft;
  final Color tileOn, tileOnInk, tileOnInk2, cardOn, tileOff;
  final Color glyphLight, glyphFan, glyphWater, glyphHeat, glyphAir;
  final Color scrim;
  final List<BoxShadow> shadowPop, shadowTile, shadowThumb;

  // iOS 설정 앱 아이콘 바탕 (두 테마 공통)
  static const symBlue = Color(0xFF007AFF);
  static const symGreen = Color(0xFF34C759);
  static const symGray = Color(0xFF8E8E93);
  static const symRed = Color(0xFFFF3B30);
  static const symOrange = Color(0xFFFF9500);
  static const symIndigo = Color(0xFF5856D6);

  static const light = HvColors(
    dark: false,
    canvas: Color(0xFFEFEEEA),
    surface: Color(0xFFFBFAF8),
    sunken: Color(0xFFEFEEEA),
    raised: Color(0xFFFBFAF8),
    line: Color(0xFFE3E1DC),
    track: Color(0xFFD3D0CA),
    fill: Color.fromRGBO(120, 113, 102, 0.12),
    thumb: Color(0xFFFDFCFA),
    ink: Color(0xFF1E1D1B),
    ink2: Color(0xFF54514C),
    ink3: Color(0xFF65625D),
    brand: Color(0xFF0071E3),
    brandDark: Color(0xFF0062C4),
    brandSoft: Color(0xFFE3EDF8),
    brandInk: Color(0xFF005FBF),
    switchOn: Color(0xFF34C759),
    ok: Color(0xFF1D7434),
    okSoft: Color(0xFFE3F1E6),
    caution: Color(0xFF805500),
    cautionSoft: Color(0xFFF8EFD6),
    warn: Color(0xFFB03000),
    warnSoft: Color(0xFFFBE9DF),
    danger: Color(0xFFC20F1E),
    dangerSoft: Color(0xFFFBE6E6),
    dangerFill: Color(0xFFC8101F),
    mutedSoft: Color(0xFFE8E6E1),
    tileOn: Color(0xFFFDFCFA),
    tileOnInk: Color(0xFF1E1D1B),
    tileOnInk2: Color(0xFF65625D),
    cardOn: Color(0xFFFDFCFA),
    tileOff: Color(0xFFE2E0DB),
    glyphLight: Color(0xFFE6A100),
    glyphFan: Color(0xFF0A9FB8),
    glyphWater: Color(0xFF0A84FF),
    glyphHeat: Color(0xFFFF8A00),
    glyphAir: Color(0xFF23966A),
    scrim: Color.fromRGBO(0, 0, 0, 0.32),
    shadowPop: [BoxShadow(color: Color.fromRGBO(0, 0, 0, 0.18), offset: Offset(0, 10), blurRadius: 40)],
    shadowTile: [
      BoxShadow(color: Color.fromRGBO(60, 50, 30, 0.06), offset: Offset(0, 1), blurRadius: 2),
      BoxShadow(color: Color.fromRGBO(60, 50, 30, 0.06), offset: Offset(0, 2), blurRadius: 8),
    ],
    shadowThumb: [
      BoxShadow(color: Color.fromRGBO(0, 0, 0, 0.12), offset: Offset(0, 3), blurRadius: 8),
      BoxShadow(color: Color.fromRGBO(0, 0, 0, 0.04), offset: Offset(0, 3), blurRadius: 1),
    ],
  );

  static const darkTheme = HvColors(
    dark: true,
    canvas: Color(0xFF0E0E0D),
    surface: Color(0xFF1C1C1A),
    sunken: Color(0xFF2A2927),
    raised: Color(0xFF393835),
    line: Color(0xFF363532),
    track: Color(0xFF3A3936),
    fill: Color.fromRGBO(118, 118, 128, 0.24),
    thumb: Color(0xFF5F5D59),
    ink: Color(0xFFF3F1ED),
    ink2: Color(0xFFB3AFA8),
    ink3: Color(0xFF8F8B85),
    brand: Color(0xFF0071E3),
    brandDark: Color(0xFF0062C4),
    brandSoft: Color(0xFF0D2A4D),
    brandInk: Color(0xFF409CFF),
    switchOn: Color(0xFF30D158),
    ok: Color(0xFF30D158),
    okSoft: Color(0xFF12301C),
    caution: Color(0xFFFFD60A),
    cautionSoft: Color(0xFF352E0B),
    warn: Color(0xFFFF9F0A),
    warnSoft: Color(0xFF3A2808),
    danger: Color(0xFFFF453A),
    dangerSoft: Color(0xFF3D1614),
    dangerFill: Color(0xFFD70015),
    mutedSoft: Color(0xFF2A2927),
    tileOn: Color(0xFFF3F1ED),
    tileOnInk: Color(0xFF1E1D1B),
    tileOnInk2: Color(0xFF65625D),
    cardOn: Color(0xFF2B2A28),
    tileOff: Color(0xFF141413),
    glyphLight: Color(0xFFE6A100),
    glyphFan: Color(0xFF0A9FB8),
    glyphWater: Color(0xFF0A84FF),
    glyphHeat: Color(0xFFFF8A00),
    glyphAir: Color(0xFF30B47F),
    scrim: Color.fromRGBO(0, 0, 0, 0.6),
    shadowPop: [BoxShadow(color: Color.fromRGBO(0, 0, 0, 0.6), offset: Offset(0, 16), blurRadius: 48)],
    shadowTile: [],
    shadowThumb: [BoxShadow(color: Color.fromRGBO(0, 0, 0, 0.3), offset: Offset(0, 3), blurRadius: 8)],
  );

  Color riskText(Risk r) => switch (r) {
        Risk.normal => ok,
        Risk.caution => caution,
        Risk.warning => warn,
        Risk.danger => danger,
        Risk.uncertain => ink2,
      };

  Color riskSoft(Risk r) => switch (r) {
        Risk.normal => okSoft,
        Risk.caution => cautionSoft,
        Risk.warning => warnSoft,
        Risk.danger => dangerSoft,
        Risk.uncertain => mutedSoft,
      };

  Color riskStrong(Risk r) => switch (r) {
        Risk.normal => ok,
        Risk.caution => caution,
        Risk.warning => warn,
        Risk.danger => danger,
        Risk.uncertain => ink3,
      };

  @override
  HvColors copyWith() => this;

  @override
  HvColors lerp(ThemeExtension<HvColors>? other, double t) => (other is HvColors && t >= 0.5) ? other : this;
}
