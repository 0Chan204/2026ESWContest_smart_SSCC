// 웹 빌드용: dart:io 가 없으므로 저장하지 않는다 (켤 때마다 처음 값).

import 'prefs_storage.dart';

PrefsStorage createPlatformPrefsStorage() => MemoryPrefsStorage();
