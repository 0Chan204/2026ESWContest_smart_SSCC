// 백엔드 기기 목록 · 실시간 봉투 → 화면 형식 (React httpSource.ts 의 buildDevices · translate ·
// applyAirState · airFromDecision 과 같은 동작). 네트워크와 분리해 단위 테스트가 쉽다.

import '../models/types.dart';
import 'parse.dart';
import 'stream_message.dart';

const historyLen = 60;

class Snapshot {
  const Snapshot({
    required this.devices,
    required this.kitchenPresence,
    required this.bathroomPresence,
    required this.location,
    required this.sensing,
    required this.session,
    required this.sessions,
    required this.events,
    required this.contacts,
    required this.policy,
    required this.fallPolicy,
    this.fall,
  });

  final List<Device> devices;
  final Presence kitchenPresence;
  final Presence bathroomPresence;
  final Location location;

  /// 최근 최종 재실 판단 (오래된 것부터)
  final List<SensingSample> sensing;
  final CookingSession? session;
  final List<CookingSession> sessions;

  /// 최신이 앞
  final List<SafetyEvent> events;
  final FallIncident? fall;
  final Contacts contacts;
  final KitchenPolicy policy;
  final FallPolicy fallPolicy;
}

class _AirReason {
  const _AirReason(this.auto, [this.reason]);
  final bool auto;
  final AirAutoReason? reason;
}

final _cookHint = RegExp(r'stove|induction|cook|인덕션|조리|요리', caseSensitive: false);

class BackendTranslator {
  /// 화면 형식 기기 목록 (실시간 메시지를 해석할 때 지금 상태가 필요하다)
  List<Device> devices = [];

  /// 이 화면에서 보낸 명령 id (최근 50개)
  final Set<String> sentCommands = <String>{};
  final Map<String, List<double>> _tempHistory = {};
  final Map<String, _AirReason> _airCommandReason = {};
  final Map<String, String?> _lastAirCommand = {};

  void rememberCommand(String commandId) {
    sentCommands.add(commandId);
    if (sentCommands.length > 50) sentCommands.remove(sentCommands.first);
  }

  void _pushTemp(String id, double t) {
    final h = [...?_tempHistory[id], t];
    _tempHistory[id] = h.length > historyLen ? h.sublist(h.length - historyLen) : h;
  }

  /// GET /snapshot 의 devices(DeviceInfo[]) + appliances(화구 상세) → 화면 기기
  List<Device> buildDevices(Obj snapshot) {
    _lastAirCommand.clear();
    final appliances = objs(snapshot['appliances']);
    final out = <Device>[];
    for (final info in objs(snapshot['devices'])) {
      final id = str(info['deviceId']);
      if (id.isEmpty) continue;
      final room = mapRoom(info['room']);
      final online = info['online'] == true;
      final auto = info['control_state'] == 'homevis';
      final curRaw = obj(info['current_state']);
      final cur = curRaw ?? const <String, dynamic>{};
      switch (info['device']) {
        case 'stove':
          Obj? ap;
          for (final a in appliances) {
            if (a['deviceId'] == id) {
              ap = a;
              break;
            }
          }
          final burners = arr(ap?['burners']);
          final burner = (burners.isNotEmpty ? mapBurner(burners.first) : null) ??
              Burner(
                burnerId: 'burner-1',
                deviceState: burnerState(cur['state']) ?? BurnerState.off,
                level: clampD(numOr(cur['level']), 0, 9).round(),
                temperature: numOr(cur['temperature'], 25),
                activeSec: 0,
              );
          if (!_tempHistory.containsKey(id)) _pushTemp(id, burner.temperature);
          out.add(InductionDevice(
            id: id,
            name: '인덕션',
            room: room,
            online: online,
            burner: burner,
            lastControl: mapPublisher(ap?['lastControl']) ?? (auto ? Publisher.system : Publisher.user),
            alarm: false,
            tempHistory: List.unmodifiable(_tempHistory[id] ?? [burner.temperature]),
          ));
        case 'light':
          // 아직 상태를 받지 못한 전등은 is_on 만 본다
          final st = curRaw ?? {'power': info['is_on'] == true ? 'on' : 'off'};
          final ls = mapLightState(st, cur['powerSaving']);
          out.add(LightDevice(
            id: id,
            name: '${roomName[room]} 조명',
            room: room,
            online: online,
            auto: auto,
            on: ls.on,
            brightness: ls.brightness,
            saving: ls.saving,
            blinking: ls.blinking,
            brightnessSteps: lightSteps,
          ));
        case 'fan':
          out.add(FanDevice(
            id: id,
            name: '${roomName[room]} 환풍기',
            room: room,
            online: online,
            auto: auto,
            on: curRaw != null ? cur['power'] == 'on' : info['is_on'] == true,
            speed: mapSpeed(cur['speed'], 2),
          ));
        case 'air_purifier':
          out.add(AirPurifierDevice(
            id: id,
            name: '공기청정기',
            room: room,
            online: online,
            auto: auto,
            on: curRaw != null ? cur['power'] == 'on' : info['is_on'] == true,
            mode: cur['mode'] == 'manual' ? AirMode.manual : AirMode.auto,
            airQuality: mapAirQuality(cur['airQuality']),
          ));
        case 'water_purifier':
          final ml = optNum(cur['lastDispensedMl']);
          out.add(PurifierDevice(
            id: id,
            name: '정수기',
            room: room,
            online: online,
            dispensing: info['is_on'] == true,
            lastDispense: (ml != null && ml != 0) ? LastDispense(at: str(info['updatedAt'], nowIso()), ml: ml, auto: auto) : null,
            autoDispensedToday: false,
          ));
        default:
          break;
      }
    }
    devices = out;
    return out;
  }

  Device? _find(Object? id) {
    for (final d in devices) {
      if (d.id == id) return d;
    }
    return null;
  }

  void _replace(Device next) {
    devices = [for (final x in devices) x.id == next.id ? next : x];
  }

  /// 서버 봉투 { event, at, data } → 화면 메시지 (모르는 이벤트는 무시)
  List<StreamMessage> translate(String event, String at, Obj data) {
    switch (event) {
      case 'burner.telemetry':
        final burners = arr(data['burners']).map(mapBurner).whereType<Burner>().toList();
        final id = str(data['deviceId']);
        if (id.isEmpty || burners.isEmpty) return const [];
        _pushTemp(id, burners.first.temperature);
        final d = _find(id);
        if (d is InductionDevice) _replace(d.copyWith(burner: burners.first));
        return [BurnerTelemetryMsg(deviceId: id, reportedAt: str(data['reportedAt'], at), burners: burners)];
      case 'presence.updated':
        final p = mapPresence(data);
        return p == null ? const [] : [PresenceMsg(p)];
      case 'safety.event':
        final e = mapEvent(data);
        return e == null ? const [] : [SafetyEventMsg(e)];
      case 'session.updated':
        final s = mapSession(data);
        return s == null ? const [] : [SessionMsg(s)];
      case 'fall.incident':
        final f = mapFall(data);
        return f == null ? const [] : [FallMsg(f)];
      case 'device.state':
        return _deviceState(at, data);
      case 'sensing.result':
        final sample = mapSensing(data);
        if (sample == null) return const [];
        return [
          LocationMsg(location: sample.room?.location ?? Location.unknown, observedAt: sample.at),
          SensingMsg(sample),
        ];
      case 'ai.decision':
        return _airFromDecision(data);
      case 'voice.status':
        final r = mapVoice(data);
        return r == null ? const [] : [VoiceMsg(r)];
      case 'voice.settings':
        final v = mapVoiceSettings(data);
        return v == null ? const [] : [VoiceSettingsMsg(v)];
      case 'command.result':
        final status = str(data['status']);
        final result = str(data['result']);
        final failed = status == 'rejected' || status == 'failed' || result == 'rejected' || result == 'failed';
        if (!failed) return const [];
        final id = str(data['deviceId']);
        return [CommandFailedMsg(deviceId: id, commandId: str(data['commandId']), status: status.isEmpty ? result : status, deviceName: _find(id)?.name)];
      case 'ai.announcement':
      case 'weather.briefing':
        // 음성 명령의 답변(voiceId 있음)은 voice.status 의 answer 로만 보여준다 (두 번 보이지 않도록)
        final vid = data['voiceId'];
        if (event == 'ai.announcement' && vid is String && vid.isNotEmpty) return const [];
        final text = str(data['text']).trim();
        if (text.isEmpty) return const [];
        return [AnnouncementMsg(id: '$event:${str(data['decisionId'], at)}', text: text.length > 500 ? text.substring(0, 500) : text, at: at)];
      default:
        return const [];
    }
  }

  List<StreamMessage> _deviceState(String at, Obj data) {
    final d = _find(data['deviceId']);
    final st = obj(data['state']);
    if (d == null || st == null) return const [];
    final lc = obj(st['lastControl']);
    final cid = lc?['commandId'];
    // 화면에서 보낸 명령의 결과면 '직접 조작', 서버 자동 조치(system)면 '자동'
    final bool auto = (cid is String && sentCommands.contains(cid))
        ? false
        : lc?['publisher'] == 'system'
            ? true
            : switch (d) { LightDevice(:final auto) => auto, FanDevice(:final auto) => auto, _ => false };
    final power = st['power'];
    final hasPower = power == 'on' || power == 'off';
    Device? next;
    switch (d) {
      case LightDevice():
        if (hasPower) {
          final ls = mapLightState(st);
          next = d.copyWith(online: true, auto: auto, on: ls.on, brightness: ls.brightness, saving: ls.saving, blinking: ls.blinking);
        }
      case FanDevice():
        if (hasPower) next = d.copyWith(online: true, auto: auto, on: power == 'on', speed: mapSpeed(st['speed'], d.speed));
      case AirPurifierDevice():
        if (hasPower) next = _applyAirState(d, st);
      case PurifierDevice():
        final ml = optNum(st['lastDispensedMl']);
        next = PurifierDevice(
          id: d.id,
          name: d.name,
          room: d.room,
          online: true,
          dispensing: st['status'] == 'dispensing',
          lastDispense: (ml != null && ml != 0) ? LastDispense(at: str(st['reportedAt'], at), ml: ml, auto: d.lastDispense?.auto ?? false) : d.lastDispense,
          autoDispensedToday: d.autoDispensedToday,
        );
      case InductionDevice():
        break;
    }
    if (next == null) return const [];
    _replace(next);
    return [DeviceMsg(next)];
  }

  /// 공기청정기 상태 → 화면 기기. 누가 바꿨는지(lastControl)로 자동 여부·이유를 정한다
  AirPurifierDevice _applyAirState(AirPurifierDevice d, Obj st) {
    final on = st['power'] == 'on';
    final lc = obj(st['lastControl']);
    final cidRaw = lc?['commandId'];
    final String? cid = cidRaw is String ? cidRaw : null;
    var auto = d.auto;
    var reason = d.autoReason;
    final known = cid != null ? _airCommandReason[cid] : null;
    if (cid != null && sentCommands.contains(cid)) {
      auto = false;
      reason = null;
    } else if (known != null) {
      auto = known.auto;
      reason = known.reason;
    } else if (lc?['publisher'] == 'system') {
      // 기기가 스스로 바꿈: 켜졌다면 공기질이 나빠서
      auto = true;
      reason = on ? AirAutoReason.air : null;
    } else if (cid != null && _lastAirCommand.containsKey(d.id) && _lastAirCommand[d.id] != cid) {
      // 이 화면이 보내지 않은 새 명령 (음성 명령 · 다른 화면 등)
      auto = false;
      reason = null;
    }
    _lastAirCommand[d.id] = cid;
    final mode = st['mode'] == 'manual' ? AirMode.manual : st['mode'] == 'auto' ? AirMode.auto : d.mode;
    return AirPurifierDevice(
      id: d.id,
      name: d.name,
      room: d.room,
      online: true,
      on: on,
      mode: mode,
      auto: auto,
      autoReason: on ? reason : null,
      airQuality: mapAirQuality(st['airQuality']) ?? d.airQuality,
    );
  }

  /// AI 판단(ai.decision)에서 공기청정기를 켠 명령을 찾아 이유를 기록한다.
  List<StreamMessage> _airFromDecision(Obj data) {
    final vid = data['voiceId'];
    final byVoice = vid is String && vid.isNotEmpty;
    final stoveOn = devices.any((x) => x is InductionDevice && x.burner.deviceState == BurnerState.on);
    final hint = _cookHint.hasMatch('${str(data['scenario'])} ${str(data['reason'])}');
    final out = <StreamMessage>[];
    for (final a in objs(data['actions'])) {
      final cid = a['commandId'];
      if (a['device'] != 'air_purifier' || cid is! String || a['status'] != 'sent') continue;
      final turnsOn = a['action'] == 'on';
      final info = (byVoice || !turnsOn) ? _AirReason(!byVoice) : _AirReason(true, (stoveOn || hint) ? AirAutoReason.induction : null);
      _airCommandReason[cid] = info;
      if (_airCommandReason.length > 50) _airCommandReason.remove(_airCommandReason.keys.first);
      // 기기 상태가 판단보다 먼저 도착한 경우
      final d = _find(a['deviceId']);
      if (d is AirPurifierDevice && _lastAirCommand[d.id] == cid) {
        final next = d.copyWith(auto: info.auto, autoReason: () => d.on ? info.reason : null);
        _replace(next);
        out.add(DeviceMsg(next));
      }
    }
    return out;
  }

  /// GET /devices 결과에서 온라인 상태가 바뀐 기기만 알린다
  List<StreamMessage> connectionChanges(Object? devicesResponse) {
    final out = <StreamMessage>[];
    for (final info in objs(obj(devicesResponse)?['items'])) {
      final d = _find(info['deviceId']);
      final online = info['online'] == true;
      if (d == null || d.online == online) continue;
      _replace(d.withOnline(online));
      out.add(ConnectionMsg(deviceId: d.id, online: online));
    }
    return out;
  }
}

/// 밝기 → 백엔드 전등이 받을 수 있는 가장 가까운 단계 (동률이면 100 쪽)
int nearestLightStep(int brightness) {
  var best = 100;
  for (final s in lightSteps) {
    if ((s - brightness).abs() < (best - brightness).abs()) best = s;
  }
  return best;
}
