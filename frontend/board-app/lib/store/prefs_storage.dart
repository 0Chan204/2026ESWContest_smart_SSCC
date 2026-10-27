// 설정 저장소. 보드는 파일 시스템이 읽기 전용이고 $HOME 만 쓸 수 있어
// $HOME/.config/homevis_gui/prefs.json 에 작은 JSON 하나를 둔다.
// 웹 빌드(dart:io 없음)는 메모리에만 둔다 — 조건부 import 로 웹에서도 컴파일된다.
//
// 읽기 · 쓰기 오류(권한 없음, 깨진 JSON, 디스크 가득 참)는 절대 앱을 멈추지 않는다:
// 읽기 실패 = 처음 값으로 시작, 쓰기 실패 = 메모리에서 계속.

import 'prefs_storage_memory.dart' if (dart.library.io) 'prefs_storage_io.dart' as platform;

abstract class PrefsStorage {
  /// 저장된 값. 없거나 읽을 수 없으면 null
  Map<String, Object?>? read();

  /// 저장. 실패해도 예외를 던지지 않고 false
  bool write(Map<String, Object?> data);

  /// 화면 · 문서에 보여줄 위치 (메모리면 null)
  String? get location;
}

/// 저장하지 않는 저장소 (웹 · 테스트 · $HOME 이 없을 때)
class MemoryPrefsStorage implements PrefsStorage {
  MemoryPrefsStorage([this._data]);
  Map<String, Object?>? _data;

  @override
  Map<String, Object?>? read() => _data == null ? null : Map.of(_data!);

  @override
  bool write(Map<String, Object?> data) {
    _data = Map.of(data);
    return true;
  }

  @override
  String? get location => null;
}

/// 이 플랫폼의 기본 저장소 (보드 · macOS = 파일, 웹 = 메모리)
PrefsStorage createPrefsStorage() => platform.createPlatformPrefsStorage();
