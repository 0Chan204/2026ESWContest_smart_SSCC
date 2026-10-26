// 화면 상태와 리듀서 (React store/HomeStore.tsx 의 reducer · 파생 값과 같은 규칙). 순수 함수라 테스트하기 쉽다.

import '../data/parse.dart' show unknownPresence;
import '../data/stream_message.dart';
import '../data/translator.dart';
import '../models/types.dart';
import '../util/labels.dart';

/// 재실 판단 결과를 몇 개까지 들고 있을지 (1초 주기 → 약 1분 반)
const sensingKeep = 90;

enum AbsenceStage { none, watch, reduce, off }

class Announcement {
  const Announcement({required this.id, required this.text, required this.at});
  final String id;
  final String text;
  final String at;
}

class HomeState {
  const HomeState({
    this.ready = false,
    this.devices = const [],
    required this.kitchenPresence,
    required this.bathroomPresence,
    this.location = Location.unknown,
    this.sensing = const [],
    this.activeSessionId,
    this.sessions = const {},
    this.events = const [],
    this.fall,
    this.contacts = const Contacts(),
    this.policy = const KitchenPolicy(),
    this.fallPolicy = const FallPolicy(),
    this.absenceStage = AbsenceStage.none,
    this.notice,
    this.fallAlertOpen = false,
    this.announcement,
    this.loadError,
  });

  factory HomeState.initial() =>
      HomeState(kitchenPresence: unknownPresence(RoomId.kitchen), bathroomPresence: unknownPresence(RoomId.bathroom));

  final bool ready;
  final List<Device> devices;
  final Presence kitchenPresence;
  final Presence bathroomPresence;
  final Location location;
  final List<SensingSample> sensing;
  final String? activeSessionId;
  final Map<String, CookingSession> sessions;

  /// 최신이 앞
  final List<SafetyEvent> events;
  final FallIncident? fall;
  final Contacts contacts;
  final KitchenPolicy policy;
  final FallPolicy fallPolicy;
  final AbsenceStage absenceStage;

  /// 방금 시스템이 수행한 안전 조치 (결과 안내 시트)
  final SafetyEvent? notice;
  final bool fallAlertOpen;

  /// AI 판정 엔진의 최근 안내 문장
  final Announcement? announcement;

  /// 처음 불러오기 실패
  final String? loadError;

  HomeState copyWith({
    bool? ready,
    List<Device>? devices,
    Presence? kitchenPresence,
    Presence? bathroomPresence,
    Location? location,
    List<SensingSample>? sensing,
    String? Function()? activeSessionId,
    Map<String, CookingSession>? sessions,
    List<SafetyEvent>? events,
    FallIncident? Function()? fall,
    Contacts? contacts,
    KitchenPolicy? policy,
    FallPolicy? fallPolicy,
    AbsenceStage? absenceStage,
    SafetyEvent? Function()? notice,
    bool? fallAlertOpen,
    Announcement? Function()? announcement,
    String? Function()? loadError,
  }) =>
      HomeState(
        ready: ready ?? this.ready,
        devices: devices ?? this.devices,
        kitchenPresence: kitchenPresence ?? this.kitchenPresence,
        bathroomPresence: bathroomPresence ?? this.bathroomPresence,
        location: location ?? this.location,
        sensing: sensing ?? this.sensing,
        activeSessionId: activeSessionId != null ? activeSessionId() : this.activeSessionId,
        sessions: sessions ?? this.sessions,
        events: events ?? this.events,
        fall: fall != null ? fall() : this.fall,
        contacts: contacts ?? this.contacts,
        policy: policy ?? this.policy,
        fallPolicy: fallPolicy ?? this.fallPolicy,
        absenceStage: absenceStage ?? this.absenceStage,
        notice: notice != null ? notice() : this.notice,
        fallAlertOpen: fallAlertOpen ?? this.fallAlertOpen,
        announcement: announcement != null ? announcement() : this.announcement,
        loadError: loadError != null ? loadError() : this.loadError,
      );

  // ── 파생 값 ──────────────────────────────────────────────────────────────
  InductionDevice? get induction {
    for (final d in devices) {
      if (d is InductionDevice) return d;
    }
    return null;
  }

  CookingSession? get session => activeSessionId == null ? null : sessions[activeSessionId];

  KitchenPhase get kitchenPhase {
    if (induction?.burner.deviceState == BurnerState.overheated) return KitchenPhase.overheat;
    return switch (absenceStage) {
      AbsenceStage.off => KitchenPhase.autoOff,
      AbsenceStage.reduce => KitchenPhase.autoReduced,
      AbsenceStage.watch => KitchenPhase.absenceWatch,
      AbsenceStage.none => KitchenPhase.normal,
    };
  }

  Risk get kitchenRisk {
    final ind = induction;
    return maxRisk([phaseRisk(kitchenPhase), ind != null && !ind.online ? Risk.uncertain : Risk.normal]);
  }

  Risk get bathroomRisk => fall?.status == FallStatus.pending ? Risk.danger : Risk.normal;

  Risk get overallRisk => maxRisk([kitchenRisk, bathroomRisk]);

  SensingSample? get latestSensing => sensing.isEmpty ? null : sensing.last;

  Device? deviceById(String? id) {
    if (id == null) return null;
    for (final d in devices) {
      if (d.id == id) return d;
    }
    return null;
  }

  SafetyEvent? eventById(String? id) {
    if (id == null) return null;
    for (final e in events) {
      if (e.eventId == id) return e;
    }
    return null;
  }
}

const _noticeTypes = {SafetyEventType.autoPowerReduced, SafetyEventType.autoPowerOff, SafetyEventType.overheatDetected};

AbsenceStage _stageAfter(SafetyEvent e, AbsenceStage current) => switch (e.type) {
      SafetyEventType.absenceDetected => AbsenceStage.watch,
      SafetyEventType.autoPowerReduced => AbsenceStage.reduce,
      SafetyEventType.autoPowerOff => AbsenceStage.off,
      SafetyEventType.userReturned || SafetyEventType.cookingEnded => AbsenceStage.none,
      _ => current,
    };

HomeState applySnapshot(HomeState state, Snapshot s) => state.copyWith(
      ready: true,
      loadError: () => null,
      devices: s.devices,
      kitchenPresence: s.kitchenPresence,
      bathroomPresence: s.bathroomPresence,
      location: s.location,
      sensing: s.sensing.length > sensingKeep ? s.sensing.sublist(s.sensing.length - sensingKeep) : s.sensing,
      activeSessionId: () => s.session?.sessionId,
      sessions: {for (final x in s.sessions) x.sessionId: x},
      events: s.events,
      fall: () => s.fall,
      contacts: s.contacts,
      policy: s.policy,
      fallPolicy: s.fallPolicy,
    );

HomeState reduceMessage(HomeState state, StreamMessage m) {
  switch (m) {
    case BurnerTelemetryMsg():
      return state.copyWith(devices: [
        for (final d in state.devices)
          if (d is InductionDevice && d.id == m.deviceId)
            () {
              final burner = m.burners.isNotEmpty ? m.burners.first : d.burner;
              final h = [...d.tempHistory, burner.temperature];
              return d.copyWith(
                burner: burner,
                online: true,
                lastControl: m.lastControl ?? d.lastControl,
                alarm: m.alarm ?? d.alarm,
                tempHistory: h.length > 60 ? h.sublist(h.length - 60) : h,
              );
            }()
          else
            d,
      ]);
    case PresenceMsg(:final presence):
      final kitchen = presence.room == RoomId.kitchen;
      return state.copyWith(
        kitchenPresence: kitchen ? presence : null,
        bathroomPresence: kitchen ? null : presence,
        absenceStage: kitchen && presence.present ? AbsenceStage.none : state.absenceStage,
      );
    case SafetyEventMsg(:final event):
      return state.copyWith(
        events: [event, ...state.events.where((x) => x.eventId != event.eventId)],
        absenceStage: event.room == RoomId.kitchen ? _stageAfter(event, state.absenceStage) : state.absenceStage,
        notice: _noticeTypes.contains(event.type) ? () => event : null,
      );
    case SessionMsg(:final session):
      return state.copyWith(
        sessions: {...state.sessions, session.sessionId: session},
        activeSessionId: () => session.active
            ? session.sessionId
            : state.activeSessionId == session.sessionId
                ? null
                : state.activeSessionId,
      );
    case FallMsg(:final fall):
      return state.copyWith(fall: () => fall, fallAlertOpen: fall.status == FallStatus.pending ? true : state.fallAlertOpen);
    case ConnectionMsg():
      return state.copyWith(devices: [for (final d in state.devices) d.id == m.deviceId ? d.withOnline(m.online) : d]);
    case DeviceMsg(:final device):
      return state.copyWith(devices: [for (final d in state.devices) d.id == device.id ? device : d]);
    case LocationMsg(:final location):
      return state.copyWith(location: location);
    case AnnouncementMsg():
      return state.copyWith(announcement: () => Announcement(id: m.id, text: m.text, at: m.at));
    case SensingMsg(:final sample):
      final last = state.latestSensing;
      if (last != null && last.at == sample.at && last.room == sample.room) return state;
      final next = [...state.sensing, sample];
      return state.copyWith(sensing: next.length > sensingKeep ? next.sublist(next.length - sensingKeep) : next);
    case VoiceMsg():
    case CommandFailedMsg():
      // 음성 패널 · 토스트가 직접 받는다 (화면 상태에는 두지 않음)
      return state;
  }
}
