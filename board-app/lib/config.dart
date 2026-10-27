// 빌드 시 --dart-define 으로 받는 설정. 키·토큰·비밀번호를 넣지 않는다.
//
//   API_BASE      백엔드 오리진 (기본 http://127.0.0.1:8000 — 보드 안 Docker 백엔드)
//   DEFAULT_MODE  normal | elderly (기본 normal). 저장된 화면 모드가 없을 때의 처음 값
//   SKIP_ONBOARDING  true 면 첫 실행 화면(모드 선택 · 권한 동의)을 건너뛴다 (키오스크 · 시험용, 기본 false)
//   CANVAS_SCALE  0 = 자동(1280×720 보다 작은 화면만 축소), 1.5 = 1920×1080 화면에서 1280×720 배치를 1.5배로

import 'models/types.dart';

const String apiBaseRaw = String.fromEnvironment('API_BASE', defaultValue: 'http://127.0.0.1:8000');
const String defaultModeRaw = String.fromEnvironment('DEFAULT_MODE', defaultValue: 'normal');
const String canvasScaleRaw = String.fromEnvironment('CANVAS_SCALE', defaultValue: '0');
const String skipOnboardingRaw = String.fromEnvironment('SKIP_ONBOARDING', defaultValue: 'false');

const String appVersion = 'HomeVIS 7.0 · board';

/// 끝의 / 를 뗀 백엔드 오리진
String apiOrigin([String raw = apiBaseRaw]) {
  var s = raw.trim();
  while (s.endsWith('/')) {
    s = s.substring(0, s.length - 1);
  }
  return s.isEmpty ? 'http://127.0.0.1:8000' : s;
}

/// REST 기준 주소 (…/api/v1)
String apiRoot([String raw = apiBaseRaw]) => '${apiOrigin(raw)}/api/v1';

/// WebSocket 주소. 다시 연결할 때는 ?since=<마지막 안전 이벤트 id>
Uri streamUri({String? since, String raw = apiBaseRaw}) {
  final base = Uri.parse('${apiRoot(raw)}/stream');
  final scheme = base.scheme == 'https' ? 'wss' : 'ws';
  return base.replace(scheme: scheme, queryParameters: since == null || since.isEmpty ? null : {'since': since});
}

AppMode defaultMode([String raw = defaultModeRaw]) => raw.trim().toLowerCase() == 'elderly' ? AppMode.elderly : AppMode.normal;

double canvasScale([String raw = canvasScaleRaw]) {
  final v = double.tryParse(raw.trim());
  if (v == null || !v.isFinite || v < 0.5 || v > 3) return 0;
  return v;
}

bool skipOnboarding([String raw = skipOnboardingRaw]) => const {'true', '1', 'yes'}.contains(raw.trim().toLowerCase());
