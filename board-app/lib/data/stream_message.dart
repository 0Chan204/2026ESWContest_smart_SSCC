import '../models/types.dart';

/// 실시간 메시지 (화면 형식). 서버 봉투 { event, at, data } 를 translator 가 바꿔 만든다.
sealed class StreamMessage {
  const StreamMessage();
}

class BurnerTelemetryMsg extends StreamMessage {
  const BurnerTelemetryMsg({required this.deviceId, required this.reportedAt, required this.burners, this.lastControl, this.alarm});
  final String deviceId;
  final String reportedAt;
  final List<Burner> burners;
  final Publisher? lastControl;
  final bool? alarm;
}

class PresenceMsg extends StreamMessage {
  const PresenceMsg(this.presence);
  final Presence presence;
}

class SafetyEventMsg extends StreamMessage {
  const SafetyEventMsg(this.event);
  final SafetyEvent event;
}

class SessionMsg extends StreamMessage {
  const SessionMsg(this.session);
  final CookingSession session;
}

class FallMsg extends StreamMessage {
  const FallMsg(this.fall);
  final FallIncident fall;
}

/// 기기 온라인 상태 변경 (GET /devices 폴링)
class ConnectionMsg extends StreamMessage {
  const ConnectionMsg({required this.deviceId, required this.online});
  final String deviceId;
  final bool online;
}

/// device.state 를 화면 기기로 바꾼 것
class DeviceMsg extends StreamMessage {
  const DeviceMsg(this.device);
  final Device device;
}

class LocationMsg extends StreamMessage {
  const LocationMsg({required this.location, required this.observedAt});
  final Location location;
  final String observedAt;
}

/// ai.announcement · weather.briefing (음성 명령 답변 제외)
class AnnouncementMsg extends StreamMessage {
  const AnnouncementMsg({required this.id, required this.text, required this.at});
  final String id;
  final String text;
  final String at;
}

class SensingMsg extends StreamMessage {
  const SensingMsg(this.sample);
  final SensingSample sample;
}

class VoiceMsg extends StreamMessage {
  const VoiceMsg(this.record);
  final VoiceRecord record;
}

/// 보드 음성 설정 변경 (WS voice.settings — 제안)
class VoiceSettingsMsg extends StreamMessage {
  const VoiceSettingsMsg(this.settings);
  final VoiceSettings settings;
}

/// command.result 중 실패(rejected · failed)
class CommandFailedMsg extends StreamMessage {
  const CommandFailedMsg({required this.deviceId, required this.commandId, required this.status, this.deviceName});
  final String deviceId;
  final String commandId;
  final String status;
  final String? deviceName;
}
