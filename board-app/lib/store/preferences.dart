// 화면 설정 (모드 · 테마 · 글자 크기). 보드는 저장소가 읽기 전용이라 메모리에만 둔다 —
// 켤 때마다 DEFAULT_MODE · 라이트 테마 · 글자 115% 로 시작한다.

import 'package:flutter/foundation.dart';

import '../config.dart';
import '../models/types.dart';

const fontScaleMin = 100;
const fontScaleMax = 130;
const fontScaleStep = 5;
const fontScaleDefault = 115;

class Preferences extends ChangeNotifier {
  Preferences({AppMode? mode}) : _mode = mode ?? defaultMode();

  AppMode _mode;
  ThemeChoice _theme = ThemeChoice.light;
  int _fontScale = fontScaleDefault;

  AppMode get mode => _mode;
  bool get elderly => _mode == AppMode.elderly;
  ThemeChoice get theme => _theme;
  int get fontScale => _fontScale;

  /// 실제 글자 배율. 어르신 모드에서만 키운다 (여백은 그대로)
  double get textScale => elderly ? _fontScale / 100 : 1;

  void setMode(AppMode m) {
    if (m == _mode) return;
    _mode = m;
    notifyListeners();
  }

  void setTheme(ThemeChoice t) {
    if (t == _theme) return;
    _theme = t;
    notifyListeners();
  }

  void setFontScale(int v) {
    final c = v < fontScaleMin ? fontScaleMin : (v > fontScaleMax ? fontScaleMax : v);
    if (c == _fontScale) return;
    _fontScale = c;
    notifyListeners();
  }
}
