import 'package:flutter/widgets.dart';

import '../../ui/icons.dart';
import '../../ui/widgets.dart';

enum PermissionKey { presence, mic, tts, contacts }

class PermissionInfo {
  const PermissionInfo(this.key, this.icon, this.color, this.title, this.desc, {this.required = false});
  final PermissionKey key;
  final IconData icon;
  final SymColor color;
  final String title;
  final String desc;
  final bool required;
}

/// HomeVIS 보드가 쓰는 기능 권한 (React permissions.ts 를 보드에 맞게).
/// 첫 실행 동의 창과 설정 > 앱 권한이 같은 목록을 쓴다.
const permissions = [
  PermissionInfo(PermissionKey.presence, Ic.radar, SymColor.blue, '재실 감지', 'Wi-Fi 신호로 공간에 사람이 있는지 판단해요. 카메라는 쓰지 않아요.',
      required: true),
  PermissionInfo(PermissionKey.mic, Ic.mic, SymColor.red, '마이크', '보드 음성 명령에 써요. 인식 방식에 따라 음성이 외부 서버로 전송될 수 있어요.'),
  PermissionInfo(PermissionKey.tts, Ic.volume, SymColor.orange, '음성 안내', '위험 알림을 소리 내어 읽어 드려요.'),
  PermissionInfo(PermissionKey.contacts, Ic.user, SymColor.green, '연락처', '낙상이 감지되면 등록한 보호자에게 문자를 보내요.'),
];
