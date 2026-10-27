import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../features/bathroom/bathroom_page.dart';
import '../features/history/history_page.dart';
import '../features/home/home_page.dart';
import '../features/kitchen/kitchen_page.dart';
import '../features/settings/settings_page.dart';
import '../features/voice/voice_controller.dart';
import '../models/types.dart';
import '../store/home_store.dart';
import '../store/preferences.dart';
import '../theme/theme.dart';
import '../theme/tokens.dart';
import '../ui/icons.dart';
import '../ui/widgets.dart';
import 'app.dart';

/// 대시보드 골격: 왼쪽 레일 + 한 화면 고정 (페이지 스크롤 없음). 처음 불러오기 전에는 연결 화면.
class AppShell extends StatelessWidget {
  const AppShell({super.key});

  @override
  Widget build(BuildContext context) {
    final c = context.hv;
    final ready = context.select<HomeStore, bool>((s) => s.state.ready);
    final error = context.select<HomeStore, String?>((s) => s.state.loadError);
    if (!ready) {
      return Scaffold(
        backgroundColor: c.canvas,
        body: error != null ? _ConnectError(message: error) : Center(child: Text('불러오는 중…', style: ts(16, color: c.ink3))),
      );
    }
    final tab = context.select<NavState, AppTab>((n) => n.tab);
    return Scaffold(
      backgroundColor: c.canvas,
      body: Row(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          const NavRail(),
          Expanded(
            child: switch (tab) {
              AppTab.home => const HomePage(),
              AppTab.kitchen => const KitchenPage(),
              AppTab.bathroom => const BathroomPage(),
              AppTab.history => const HistoryPage(),
              AppTab.settings => const SettingsPage(),
            },
          ),
        ],
      ),
    );
  }
}

/// 처음 불러오기 실패 (보드 부팅 직후 백엔드가 늦게 뜨는 경우)
class _ConnectError extends StatelessWidget {
  const _ConnectError({required this.message});
  final String message;

  @override
  Widget build(BuildContext context) {
    final c = context.hv;
    return Center(
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 24),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Text('서버에 연결하지 못했어요', style: ts(20, weight: w600, color: c.ink)),
            const SizedBox(height: 12),
            ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 448),
              child: Text(message, textAlign: TextAlign.center, style: ts(15, color: c.ink2, height: 1.45)),
            ),
            const SizedBox(height: 20),
            HvButton(label: '다시 시도', variant: BtnVariant.primary, onPressed: () => context.read<HomeStore>().retryLoad()),
          ],
        ),
      ),
    );
  }
}

/// 왼쪽 메뉴. iPad 탭 막대처럼 선택된 항목만 파란 글자 + 흰 바탕. 아래에 마이크 버튼(음성 명령을 켰을 때)과 호출어 대기 표시.
class NavRail extends StatelessWidget {
  const NavRail({super.key});

  @override
  Widget build(BuildContext context) {
    final c = context.hv;
    final elderly = context.elderly;
    final tab = context.select<NavState, AppTab>((n) => n.tab);
    final kitchenRisk = context.select<HomeStore, Risk>((s) => s.state.kitchenRisk);
    final bathroomRisk = context.select<HomeStore, Risk>((s) => s.state.bathroomRisk);
    final items = <(AppTab, String, IconData, Risk?)>[
      (AppTab.home, '홈', Ic.house, null),
      (AppTab.kitchen, '주방', Ic.kitchen, kitchenRisk),
      (AppTab.bathroom, '욕실', Ic.bath, bathroomRisk),
      (AppTab.history, elderly ? '안전 기록' : '기록', Ic.records, null),
      (AppTab.settings, '설정', Ic.settings, null),
    ];
    return Container(
      width: elderly ? 112 : 88,
      decoration: BoxDecoration(color: c.canvas, border: Border(right: BorderSide(color: c.line))),
      padding: const EdgeInsets.only(top: 24, bottom: 20, left: 8, right: 8),
      child: Column(
        children: [
          Text('HomeVIS', style: ts(13, weight: w700, color: c.ink, tracking: -0.01)),
          const SizedBox(height: 20),
          for (final (t, label, icon, risk) in items)
            Padding(
              padding: const EdgeInsets.only(bottom: 6),
              child: Pressable(
                onTap: () => context.read<NavState>().go(t),
                semanticLabel: label,
                child: Container(
                  width: double.infinity,
                  padding: const EdgeInsets.symmetric(vertical: 10),
                  decoration: BoxDecoration(color: tab == t ? c.surface : Colors.transparent, borderRadius: BorderRadius.circular(12)),
                  child: Column(
                    children: [
                      Stack(
                        clipBehavior: Clip.none,
                        children: [
                          Icon(icon, size: elderly ? 28 : 24, color: tab == t ? c.brandInk : c.ink3),
                          if (risk != null && risk != Risk.normal)
                            Positioned(
                              top: -2,
                              right: -4,
                              child: SoftPulse(
                                active: risk == Risk.danger,
                                child: Container(
                                  width: 10,
                                  height: 10,
                                  decoration: BoxDecoration(
                                    color: c.riskStrong(risk),
                                    shape: BoxShape.circle,
                                    border: Border.all(color: c.canvas, width: 2),
                                  ),
                                ),
                              ),
                            ),
                        ],
                      ),
                      const SizedBox(height: 4),
                      Text(label,
                          style: ts(elderly ? 16 : 12, weight: w500, color: tab == t ? c.brandInk : c.ink3),
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis),
                    ],
                  ),
                ),
              ),
            ),
          const Spacer(),
          const _VoiceButton(),
        ],
      ),
    );
  }
}

/// 마이크 버튼 (React VoiceButton). 누르면 보드 마이크로 듣기 시작, 듣는 중에 누르면 멈춤.
/// 서버가 호출어를 기다리는 중(standby)이면 주황 점 + '호출어 대기' — 음성 명령을 꺼 두었어도 마이크가 켜져 있음을 알린다.
class _VoiceButton extends StatelessWidget {
  const _VoiceButton();

  @override
  Widget build(BuildContext context) {
    final c = context.hv;
    final elderly = context.elderly;
    final enabled = context.select<Preferences, bool>((p) => p.voiceCommands);
    final active = context.select<VoiceController, bool>((v) => v.open);
    final standby = context.select<VoiceController, bool>((v) => v.standby);
    if (!enabled && !standby) return const SizedBox.shrink();
    final size = elderly ? 68.0 : 56.0;
    final dot = Container(
      width: 12,
      height: 12,
      decoration: BoxDecoration(color: HvColors.symOrange, shape: BoxShape.circle, border: Border.all(color: c.canvas, width: 2)),
    );
    return Column(
      mainAxisSize: MainAxisSize.min,
      children: [
        if (enabled)
          Pressable(
            onTap: () => context.read<VoiceController>().toggleListen(),
            semanticLabel: standby ? '음성으로 말하기 · 호출어 대기 중' : '음성으로 말하기',
            child: Stack(
              clipBehavior: Clip.none,
              children: [
                Container(
                  width: size,
                  height: size,
                  decoration: BoxDecoration(color: active ? c.brandDark : c.brand, shape: BoxShape.circle),
                  child: Icon(Ic.mic, size: elderly ? 28 : 24, color: Colors.white),
                ),
                if (standby) Positioned(top: 2, right: 2, child: dot),
              ],
            ),
          )
        else
          Semantics(label: '호출어 대기 중 · 마이크 켜짐', child: dot),
        if (standby)
          Padding(
            padding: const EdgeInsets.only(top: 6),
            child: ExcludeSemantics(
              child: Text('호출어 대기', style: ts(elderly ? 14 : 11, weight: w500, color: c.ink3), maxLines: 1),
            ),
          ),
      ],
    );
  }
}
