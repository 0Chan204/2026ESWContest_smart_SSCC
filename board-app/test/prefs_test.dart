import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:homevis_gui/models/types.dart';
import 'package:homevis_gui/store/preferences.dart';
import 'package:homevis_gui/store/prefs_storage.dart';
import 'package:homevis_gui/store/prefs_storage_io.dart';

void main() {
  late Directory tmp;
  late String base;

  setUp(() {
    tmp = Directory.systemTemp.createTempSync('homevis_prefs_');
    base = '${tmp.path}/.config/homevis_gui';
  });
  tearDown(() => tmp.deleteSync(recursive: true));

  test('처음 실행: 파일 없음 → 모드 선택 · 동의 전, DEFAULT_MODE 기본값', () {
    final p = Preferences.load(FilePrefsStorage(base), fallbackMode: AppMode.elderly);
    expect(p.modeChosen, isFalse);
    expect(p.consentAnswered, isFalse);
    expect(p.mode, AppMode.elderly);
    expect(p.voiceCommands, isFalse);
    expect(p.readAloud, isTrue);
    expect(p.theme, ThemeChoice.light);
    expect(p.fontScale, fontScaleDefault);
    expect(File('$base/prefs.json').existsSync(), isFalse); // 읽기만으로는 만들지 않는다
  });

  test('저장 → 다시 켜면 그대로 (폴더도 만든다)', () {
    final s = FilePrefsStorage(base);
    final p = Preferences.load(s);
    p.setMode(AppMode.elderly);
    p.answerConsent(true);
    p.setTheme(ThemeChoice.dark);
    p.setFontScale(125);
    p.setReadAloud(false);
    expect(p.lastWriteFailed, isFalse);
    expect(File('$base/prefs.json').existsSync(), isTrue);
    expect(File('$base/prefs.json.tmp').existsSync(), isFalse);

    final q = Preferences.load(FilePrefsStorage(base));
    expect(q.modeChosen, isTrue);
    expect(q.mode, AppMode.elderly);
    expect(q.consentAnswered, isTrue);
    expect(q.voiceCommands, isTrue); // 허용 → 음성 명령 켜짐
    expect(q.readAloud, isFalse);
    expect(q.theme, ThemeChoice.dark);
    expect(q.fontScale, 125);
  });

  test('허용 안 함 → 음성 명령은 꺼진 채, 답한 것은 저장', () {
    final p = Preferences.load(FilePrefsStorage(base));
    p.setMode(AppMode.normal);
    p.answerConsent(false);
    final q = Preferences.load(FilePrefsStorage(base));
    expect(q.consentAnswered, isTrue);
    expect(q.voiceCommands, isFalse);
    expect(q.readAloud, isTrue);
  });

  test('깨진 JSON · 이상한 값 → 처음 값으로 시작하고 계속 동작, 다음 저장이 고친다', () {
    Directory(base).createSync(recursive: true);
    final f = File('$base/prefs.json')..writeAsStringSync('{"mode": "elderly", "modeCho');
    final p = Preferences.load(FilePrefsStorage(base));
    expect(p.modeChosen, isFalse);
    p.setMode(AppMode.normal);
    expect(Preferences.load(FilePrefsStorage(base)).modeChosen, isTrue);

    f.writeAsStringSync('[1, 2, 3]');
    expect(Preferences.load(FilePrefsStorage(base)).modeChosen, isFalse);

    f.writeAsStringSync(
        '{"modeChosen": true, "mode": "giant", "consentAnswered": "yes", "voiceCommands": 1, "theme": "neon", "fontScale": 999}');
    final q = Preferences.load(FilePrefsStorage(base));
    expect(q.modeChosen, isFalse); // 모르는 모드면 다시 고르게
    expect(q.consentAnswered, isFalse);
    expect(q.voiceCommands, isFalse);
    expect(q.theme, ThemeChoice.light);
    expect(q.fontScale, fontScaleMax); // 범위로 자른다

    f.writeAsStringSync('x' * (70 * 1024)); // 너무 큰 파일은 설정으로 보지 않는다
    expect(Preferences.load(FilePrefsStorage(base)).modeChosen, isFalse);
  });

  test('쓸 수 없는 위치 → 예외 없이 메모리에서 계속', () {
    // 폴더 자리에 파일이 있어 만들 수 없다
    File('${tmp.path}/blocked').writeAsStringSync('x');
    final p = Preferences.load(FilePrefsStorage('${tmp.path}/blocked/homevis_gui'));
    p.setMode(AppMode.elderly);
    p.answerConsent(true);
    expect(p.lastWriteFailed, isTrue);
    expect(p.mode, AppMode.elderly);
    expect(p.modeChosen, isTrue);
    expect(p.voiceCommands, isTrue);
  });

  test('SKIP_ONBOARDING: 첫 실행 화면을 건너뛰지만 저장값은 바꾸지 않는다', () {
    final p = Preferences.load(FilePrefsStorage(base), skipOnboarding: true);
    expect(p.modeChosen, isTrue);
    expect(p.consentAnswered, isTrue);
    p.setTheme(ThemeChoice.dark);
    final q = Preferences.load(FilePrefsStorage(base));
    expect(q.modeChosen, isFalse);
    expect(q.theme, ThemeChoice.dark);
  });

  test('메모리 저장소 · 기본 저장소 위치', () {
    final m = MemoryPrefsStorage();
    final p = Preferences.load(m)..setMode(AppMode.elderly);
    expect(Preferences.load(m).mode, AppMode.elderly);
    expect(p.storageLocation, isNull);
    final d = createPrefsStorage();
    // VM 테스트에서는 파일 저장소 ($HOME/.config/homevis_gui/prefs.json). 읽기만 하고 쓰지 않는다
    if (Platform.environment['HOME']?.isNotEmpty == true) {
      expect(d.location, endsWith('.config${Platform.pathSeparator}homevis_gui${Platform.pathSeparator}prefs.json'));
    }
  });
}
