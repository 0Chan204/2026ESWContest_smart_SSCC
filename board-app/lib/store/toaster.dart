// 화면 오른쪽 아래 알림 (React sonner 토스트 자리)

import 'dart:async';

import 'package:flutter/foundation.dart';

class ToastItem {
  ToastItem(this.id, this.text, this.error);
  final int id;
  final String text;
  final bool error;
}

class Toaster extends ChangeNotifier {
  final List<ToastItem> items = [];
  final Map<int, Timer> _timers = {};
  int _seq = 0;
  bool _disposed = false;

  void show(String text, {bool error = false, Duration duration = const Duration(seconds: 3)}) {
    if (_disposed || text.trim().isEmpty) return;
    final item = ToastItem(++_seq, text.trim(), error);
    items.add(item);
    // 한 번에 3개까지만
    while (items.length > 3) {
      _timers.remove(items.first.id)?.cancel();
      items.removeAt(0);
    }
    _timers[item.id] = Timer(duration, () => dismiss(item.id));
    notifyListeners();
  }

  void dismiss(int id) {
    if (_disposed) return;
    _timers.remove(id)?.cancel();
    final before = items.length;
    items.removeWhere((t) => t.id == id);
    if (items.length != before) notifyListeners();
  }

  @override
  void dispose() {
    _disposed = true;
    for (final t in _timers.values) {
      t.cancel();
    }
    super.dispose();
  }
}
