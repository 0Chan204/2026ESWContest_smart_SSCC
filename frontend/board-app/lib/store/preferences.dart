// 화면 설정 (모드 · 테마 · 글자 크기 · 첫 실행 · 권한). React PreferencesContext.
//
// 보드: $HOME/.config/homevis_gui/prefs.json 에 저장한다 (prefs_storage.dart). 웹 · 테스트는 메모리만.
// 저장된 값은 항상 검사해서 읽는다 — 모르는 값 · 깨진 파일이면 처음 값으로 시작한다.
// 호출어(wake word)는 보드 음성 서비스(백엔드)가 가진 설정이라 여기 두지 않는다 (VoiceController).

import 'package:flutter/foundation.dart';

import '../config.dart';
import '../models/types.dart';
import 'prefs_storage.dart';

const fontScaleMin = 100;
const fontScaleMax = 130;
const fontScaleStep = 5;
const fontScaleDefault = 115;

const _version = 1;

class Preferences extends ChangeNotifier {
  /// 메모리 설정. [onboarded] 가 true 면 첫 실행 화면(모드 선택 · 권한 동의)을 건너뛴다 (테스트 · 고정 모드).
  Preferences({AppMode? mode, bool onboarded = true, PrefsStorage? storage, bool voiceCommands = false, bool readAloud = true})
      : _storage = storage ?? MemoryPrefsStorage(),
        _skip = false,
        _mode = mode ?? defaultMode(),
        _modeChosen = onboarded,
        _consentAnswered = onboarded,
        _voiceCommands = voiceCommands,
        _readAloud = readAloud;

  /// 저장소에서 읽어 시작한다. [skipOnboarding] 은 키오스크 · 시험용 (저장값은 바꾸지 않는다)
  Preferences.load(PrefsStorage storage, {bool skipOnboarding = false, AppMode? fallbackMode})
      : _storage = storage,
        _mode = fallbackMode ?? defaultMode(),
        _skip = skipOnboarding {
    final raw = storage.read();
    if (raw != null) _apply(raw);
  }

  final PrefsStorage _storage;
  final bool _skip;

  AppMode _mode;
  bool _modeChosen = false;
  bool _consentAnswered = false;
  bool _voiceCommands = false;
  bool _readAloud = true;
  ThemeChoice _theme = ThemeChoice.light;
  int _fontScale = fontScaleDefault;

  /// 마지막 저장이 실패했는지 (화면에는 보이지 않고 메모리에서 계속)
  bool lastWriteFailed = false;

  AppMode get mode => _mode;
  bool get elderly => _mode == AppMode.elderly;
  ThemeChoice get theme => _theme;
  int get fontScale => _fontScale;

  /// 최초 화면 모드 선택을 마쳤는지
  bool get modeChosen => _modeChosen || _skip;

  /// 첫 실행 권한 동의 창에 답했는지
  bool get consentAnswered => _consentAnswered || _skip;

  /// 음성 명령(보드 마이크) 사용. 개인정보 관점에서 기본 꺼짐
  bool get voiceCommands => _voiceCommands;

  /// 위험 알림 · 답변을 소리 내어 읽기 (Speaker 로 가는 길을 여닫는다)
  bool get readAloud => _readAloud;

  String? get storageLocation => _storage.location;

  /// 실제 글자 배율. 어르신 모드에서만 키운다 (여백은 그대로)
  double get textScale => elderly ? _fontScale / 100 : 1;

  // ── 저장 형식 ──────────────────────────────────────────────────────────
  Map<String, Object?> toJson() => {
        'v': _version,
        'modeChosen': _modeChosen,
        'mode': _mode.name,
        'consentAnswered': _consentAnswered,
        'voiceCommands': _voiceCommands,
        'readAloud': _readAloud,
        'theme': _theme.name,
        'fontScale': _fontScale,
      };

  void _apply(Map<String, Object?> j) {
    bool? b(String k) => j[k] is bool ? j[k] as bool : null;
    final mode = j['mode'];
    final chosen = b('modeChosen') ?? false;
    if (chosen && (mode == 'normal' || mode == 'elderly')) {
      _mode = mode == 'elderly' ? AppMode.elderly : AppMode.normal;
      _modeChosen = true;
    }
    _consentAnswered = b('consentAnswered') ?? false;
    _voiceCommands = b('voiceCommands') ?? false;
    _readAloud = b('readAloud') ?? true;
    for (final t in ThemeChoice.values) {
      if (t.name == j['theme']) _theme = t;
    }
    final fs = j['fontScale'];
    if (fs is num && fs.isFinite) _fontScale = _clampScale(fs.round());
  }

  void _save() {
    lastWriteFailed = !_storage.write(toJson());
  }

  void _changed() {
    _save();
    notifyListeners();
  }

  static int _clampScale(int v) => v < fontScaleMin ? fontScaleMin : (v > fontScaleMax ? fontScaleMax : v);

  // ── 바꾸기 ──────────────────────────────────────────────────────────────
  /// 화면 모드 (최초 선택 화면 · 설정). 고르면 첫 실행 모드 선택은 끝난다
  void setMode(AppMode m) {
    if (m == _mode && _modeChosen) return;
    _mode = m;
    _modeChosen = true;
    _changed();
  }

  void setTheme(ThemeChoice t) {
    if (t == _theme) return;
    _theme = t;
    _changed();
  }

  void setFontScale(int v) {
    final c = _clampScale(v);
    if (c == _fontScale) return;
    _fontScale = c;
    _changed();
  }

  void setVoiceCommands(bool on) {
    if (on == _voiceCommands) return;
    _voiceCommands = on;
    _changed();
  }

  void setReadAloud(bool on) {
    if (on == _readAloud) return;
    _readAloud = on;
    _changed();
  }

  /// 권한 동의 창 응답. 허용하면 음성 명령 · 음성 안내를 켠다 (호출어는 켜지 않는다)
  void answerConsent(bool granted) {
    if (granted) {
      _voiceCommands = true;
      _readAloud = true;
    }
    _consentAnswered = true;
    _changed();
  }
}
