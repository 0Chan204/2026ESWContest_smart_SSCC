// 보드 · 데스크톱용 파일 저장소: <기준 폴더>/prefs.json
// 기준 폴더는 $HOME/.config/homevis_gui (테스트는 임시 폴더를 넘긴다).

import 'dart:convert';
import 'dart:io';

import 'prefs_storage.dart';

/// 이보다 큰 파일은 설정 파일로 보지 않는다
const _maxBytes = 64 * 1024;

class FilePrefsStorage implements PrefsStorage {
  FilePrefsStorage(this.baseDir);

  /// prefs.json 이 들어갈 폴더
  final String baseDir;

  String get _path => '$baseDir${Platform.pathSeparator}prefs.json';

  @override
  String get location => _path;

  @override
  Map<String, Object?>? read() {
    try {
      final f = File(_path);
      if (!f.existsSync() || f.lengthSync() > _maxBytes) return null;
      final v = jsonDecode(f.readAsStringSync());
      if (v is! Map) return null;
      return v.map((k, value) => MapEntry(k.toString(), value as Object?));
    } catch (_) {
      return null; // 깨진 JSON · 권한 없음 → 처음 값
    }
  }

  @override
  bool write(Map<String, Object?> data) {
    try {
      Directory(baseDir).createSync(recursive: true);
      // 쓰다가 전원이 꺼져도 반쯤 쓴 파일이 남지 않게: 임시 파일에 쓰고 이름을 바꾼다
      final tmp = File('$_path.tmp');
      tmp.writeAsStringSync(jsonEncode(data), flush: true);
      tmp.renameSync(_path);
      return true;
    } catch (_) {
      return false; // 메모리에서 계속
    }
  }
}

PrefsStorage createPlatformPrefsStorage() {
  try {
    final home = Platform.environment['HOME'];
    if (home == null || home.trim().isEmpty) return MemoryPrefsStorage();
    final sep = Platform.pathSeparator;
    return FilePrefsStorage('$home$sep.config${sep}homevis_gui');
  } catch (_) {
    return MemoryPrefsStorage();
  }
}
