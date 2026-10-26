// 화면 상태 · 동작 (React HomeStoreProvider). 화면은 이 스토어만 알고, 스토어는 HomeSource 만 안다.

import 'dart:async';

import 'package:flutter/foundation.dart';

import '../data/home_source.dart';
import '../data/stream_message.dart';
import '../data/translator.dart';
import '../models/types.dart';
import 'home_state.dart';
import 'toaster.dart';

class HomeStore extends ChangeNotifier {
  HomeStore({required this.source, required this.toaster});

  final HomeSource source;
  final Toaster toaster;

  HomeState _state = HomeState.initial();
  HomeState get state => _state;

  Weather? _weather;
  Weather? get weather => _weather;

  /// 마지막으로 상태를 확인한 시각
  DateTime? checkedAt;

  /// WebSocket 연결 여부 (정보 화면 표시용)
  bool streamConnected = false;

  final _listeners = <StreamListener>{};
  void Function()? _unsubscribe;
  Timer? _weatherTimer;
  int _attempt = 0;
  bool _disposed = false;

  /// 실시간 메시지를 직접 받는다 (음성 패널 · 토스트). 해제 함수를 돌려준다
  void Function() subscribeStream(StreamListener l) {
    _listeners.add(l);
    return () => _listeners.remove(l);
  }

  void _set(HomeState next) {
    if (_disposed || identical(next, _state)) return;
    _state = next;
    notifyListeners();
  }

  /// 처음 불러오기 + 실시간 구독 + 날씨 (10분마다)
  void start() {
    _load();
    _weatherTimer ??= Timer.periodic(const Duration(minutes: 10), (_) => _loadWeather());
    _loadWeather();
  }

  void _load() {
    final attempt = ++_attempt;
    _set(_state.copyWith(loadError: () => null));
    source.loadSnapshot().then((snapshot) {
      if (_disposed || attempt != _attempt) return;
      _set(applySnapshot(_state, snapshot));
      checkedAt = DateTime.now();
      // 부팅 직후처럼 날씨를 아직 못 받았으면 바로 다시 (보통은 10분마다)
      if (_weather == null) _loadWeather();
    }).catchError((Object e) {
      if (_disposed || attempt != _attempt) return;
      _set(_state.copyWith(loadError: () => e is ApiError ? e.message : '서버에 연결하지 못했어요.'));
    });
    _unsubscribe?.call();
    _unsubscribe = source.subscribe(_onMessage, onConnection: (c) {
      if (_disposed || streamConnected == c) return;
      streamConnected = c;
      notifyListeners();
    });
  }

  void _onMessage(StreamMessage m) {
    if (_disposed) return;
    _set(reduceMessage(_state, m));
    if (m is CommandFailedMsg) {
      toaster.show('${m.deviceName ?? '기기'} 제어에 실패했어요', error: true);
    }
    for (final l in List.of(_listeners)) {
      try {
        l(m);
      } catch (_) {
        // 듣는 쪽 오류가 다른 화면을 막지 않게
      }
    }
  }

  void retryLoad() => _load();

  Future<void> _loadWeather() async {
    try {
      final w = await source.loadWeather();
      if (_disposed) return;
      _weather = w;
      notifyListeners();
    } catch (_) {
      // 날씨는 없어도 된다
    }
  }

  Future<void> controlDevice(String id, DeviceControl control) async {
    try {
      await source.controlDevice(id, control);
    } catch (e) {
      toaster.show(e is ApiError ? e.message : '기기를 제어하지 못했어요.', error: true);
    }
  }

  Future<void> submitFeedback(String eventId, Verdict verdict) async {
    try {
      final fb = await source.submitFeedback(eventId, verdict);
      _set(_state.copyWith(events: [for (final e in _state.events) e.eventId == eventId ? e.withFeedback(fb) : e]));
    } catch (e) {
      toaster.show(e is ApiError ? e.message : '피드백을 보내지 못했어요.', error: true);
    }
  }

  /// 기기 상태를 서버에서 다시 받아온다 (너무 빨리 끝나면 눌렀는지 알 수 없어 최소 0.9초)
  Future<void> refresh() async {
    try {
      final results = await Future.wait([source.loadSnapshot(), Future<void>.delayed(const Duration(milliseconds: 900))]);
      _set(applySnapshot(_state, results[0] as Snapshot));
      checkedAt = DateTime.now();
    } catch (e) {
      toaster.show(e is ApiError ? e.message : '서버에 연결하지 못했어요.', error: true);
    }
  }

  /// 끊긴 기기 다시 연결 시도. 실제 연결은 기기·게이트웨이가 다시 붙어야 하므로 상태를 다시 확인만 한다
  Future<bool> reconnect(String deviceId) async {
    await Future<void>.delayed(const Duration(milliseconds: 1400));
    try {
      final snapshot = await source.loadSnapshot();
      _set(applySnapshot(_state, snapshot));
      checkedAt = DateTime.now();
      for (final d in snapshot.devices) {
        if (d.id == deviceId) return d.online;
      }
      return false;
    } catch (_) {
      return false;
    }
  }

  void dismissNotice() => _set(_state.copyWith(notice: () => null));

  void setFallAlert(bool open) => _set(_state.copyWith(fallAlertOpen: open));

  @override
  void dispose() {
    _disposed = true;
    _unsubscribe?.call();
    _weatherTimer?.cancel();
    super.dispose();
  }
}
