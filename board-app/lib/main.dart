// HomeVIS 보드 화면 (LG ATLAS OS · Raspberry Pi 5). React v5 대시보드를 Flutter 로 옮긴 것.
//
//   flutter run -d chrome --dart-define=API_BASE=http://127.0.0.1:8000
//   flutter-atlas build atlas --ipk --release --dart-define=API_BASE=http://127.0.0.1:8000
//
// 설정은 config.dart 의 --dart-define 만 받는다 (키 · 토큰 없음).

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import 'app/app.dart';

void main() {
  WidgetsFlutterBinding.ensureInitialized();
  // 전체화면 (보드는 창 관리자가 없다. 다른 플랫폼에서는 무시된다)
  SystemChrome.setEnabledSystemUIMode(SystemUiMode.immersiveSticky);
  runApp(const HomeVisApp());
}
