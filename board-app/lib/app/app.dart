import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../data/home_source.dart';
import '../features/alerts/action_notice_sheet.dart';
import '../features/alerts/announcements.dart';
import '../features/alerts/fall_alert_sheet.dart';
import '../features/voice/voice_controller.dart';
import '../features/voice/voice_panel.dart';
import '../models/types.dart';
import '../store/home_store.dart';
import '../store/preferences.dart';
import '../store/speaker.dart';
import '../store/toaster.dart';
import '../theme/theme.dart';
import '../theme/tokens.dart';
import '../ui/toast_host.dart';
import 'app_shell.dart';
import 'canvas.dart';

enum AppTab { home, kitchen, bathroom, history, settings }

/// 탭 전환만 한다 (보드는 전체화면 고정 — 라우팅 · 뒤로가기 없음)
class NavState extends ChangeNotifier {
  AppTab _tab = AppTab.home;
  String _settingsSection = 'display';

  AppTab get tab => _tab;
  String get settingsSection => _settingsSection;

  void go(AppTab tab, {String? section}) {
    _tab = tab;
    if (section != null) _settingsSection = section;
    notifyListeners();
  }

  void setSection(String s) {
    _settingsSection = s;
    notifyListeners();
  }
}

class HomeVisApp extends StatelessWidget {
  const HomeVisApp({super.key, this.source, this.speaker = const SilentSpeaker(), this.preferences, this.autoStart = true});

  final HomeSource? source;
  final Speaker speaker;
  final Preferences? preferences;

  /// 테스트에서 네트워크 없이 그릴 때 false
  final bool autoStart;

  @override
  Widget build(BuildContext context) {
    return MultiProvider(
      providers: [
        ChangeNotifierProvider<Preferences>(create: (_) => preferences ?? Preferences()),
        ChangeNotifierProvider<Toaster>(create: (_) => Toaster()),
        Provider<Speaker>.value(value: speaker),
        ChangeNotifierProvider<NavState>(create: (_) => NavState()),
        ChangeNotifierProvider<HomeStore>(create: (ctx) {
          final store = HomeStore(source: source ?? HomeSource(), toaster: ctx.read<Toaster>());
          if (autoStart) store.start();
          return store;
        }),
        ChangeNotifierProvider<VoiceController>(
          create: (ctx) => VoiceController(store: ctx.read<HomeStore>(), speaker: ctx.read<Speaker>()),
        ),
      ],
      child: const _ThemedApp(),
    );
  }
}

class _ThemedApp extends StatelessWidget {
  const _ThemedApp();

  @override
  Widget build(BuildContext context) {
    final theme = context.select<Preferences, ThemeChoice>((p) => p.theme);
    final platformDark = MediaQuery.platformBrightnessOf(context) == Brightness.dark;
    final dark = theme == ThemeChoice.dark || (theme == ThemeChoice.system && platformDark);
    return MaterialApp(
      title: 'HomeVIS',
      debugShowCheckedModeBanner: false,
      theme: buildTheme(dark ? HvColors.darkTheme : HvColors.light),
      builder: (context, child) => _Frame(child: child ?? const SizedBox.shrink()),
      home: const AppShell(),
    );
  }
}

/// 화면 맞춤 + 어르신 글자 배율 + 화면 전체를 덮는 알림 (낙상 · 안전 조치 · 음성 · 토스트)
class _Frame extends StatelessWidget {
  const _Frame({required this.child});
  final Widget child;

  @override
  Widget build(BuildContext context) {
    final scale = context.select<Preferences, double>((p) => p.textScale);
    final c = context.hv;
    return ColoredBox(
      color: c.canvas,
      child: ScaledCanvas(
        child: Builder(builder: (context) {
          return MediaQuery(
            data: MediaQuery.of(context).copyWith(textScaler: TextScaler.linear(scale)),
            child: DefaultTextStyle(
              style: ts(16, color: c.ink),
              child: Stack(
                children: [
                  Positioned.fill(child: child),
                  const Positioned.fill(child: _GlobalOverlays()),
                ],
              ),
            ),
          );
        }),
      ),
    );
  }
}

class _GlobalOverlays extends StatelessWidget {
  const _GlobalOverlays();

  @override
  Widget build(BuildContext context) {
    final ready = context.select<HomeStore, bool>((s) => s.state.ready);
    return Stack(
      children: [
        if (ready) const AnnouncementWatcher(),
        if (ready) const Positioned.fill(child: ActionNoticeLayer()),
        if (ready) const Positioned.fill(child: FallAlertLayer()),
        if (ready) const VoicePanelLayer(),
        const ToastHost(),
      ],
    );
  }
}
