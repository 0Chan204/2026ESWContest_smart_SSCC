import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../../app/app.dart';
import '../../app/canvas.dart';
import '../../models/types.dart';
import '../../store/home_state.dart';
import '../../store/home_store.dart';
import '../../theme/theme.dart';
import '../../ui/icons.dart';
import '../../ui/widgets.dart';
import '../../util/format.dart';

enum BannerTone { danger, warn, caution, muted }

class BannerInfo {
  const BannerInfo(this.tone, this.icon, this.title, this.detail, {this.actionLabel, this.goTab, this.openFall = false});
  final BannerTone tone;
  final IconData icon;
  final String title;
  final String detail;
  final String? actionLabel;
  final AppTab? goTab;
  final bool openFall;
}

/// 가장 급한 것 하나. 우선순위: 낙상(응답 대기) > 과열 > 자동 차단 > 화력 저감 > 이탈 관찰 > 기기 연결 끊김
BannerInfo? bannerFor(HomeState s, DateTime now) {
  final k = s.kitchenPresence;
  final mult = k.zone == Zone.near ? s.policy.nearZoneMultiplier : 1;
  final offline = s.devices.where((d) => !d.online).toList();
  final fall = s.fall;
  final phase = s.kitchenPhase;
  if (fall != null && fall.status == FallStatus.pending && !s.fallAlertOpen) {
    return BannerInfo(BannerTone.danger, Ic.alert, '욕실 낙상 감지',
        '보호자 응답이 없으면 ${formatCountdown(secondsUntil(fall.autoReportAt, now))} 후 자동 신고',
        actionLabel: '자세히', openFall: true);
  }
  if (phase == KitchenPhase.overheat) {
    return BannerInfo(BannerTone.danger, Ic.flame, '인덕션 과열 ${(s.induction?.burner.temperature ?? 0).round()}°C', '식을 때까지 켤 수 없어요',
        actionLabel: '주방', goTab: AppTab.kitchen);
  }
  if (phase == KitchenPhase.autoOff) {
    return const BannerInfo(BannerTone.danger, Ic.flame, '인덕션 전원 자동 차단', '주방을 오래 비우셨어요', actionLabel: '주방', goTab: AppTab.kitchen);
  }
  if (phase == KitchenPhase.autoReduced) {
    return BannerInfo(BannerTone.warn, Ic.userX, '화력 ${s.policy.reduceToLevel.round()}단으로 낮춤',
        '부재 ${formatDuration(k.absentSec)} · ${(s.policy.offAfterSec * mult / 60).round()}분이 되면 전원을 꺼요',
        actionLabel: '주방', goTab: AppTab.kitchen);
  }
  if (phase == KitchenPhase.absenceWatch) {
    return BannerInfo(BannerTone.caution, Ic.userX, '조리 중 주방 비어 있음',
        '부재 ${formatDuration(k.absentSec)} · ${(s.policy.reduceAfterSec * mult / 60).round()}분이 되면 화력을 낮춰요',
        actionLabel: '주방', goTab: AppTab.kitchen);
  }
  if (offline.isNotEmpty) {
    return BannerInfo(BannerTone.muted, Ic.wifiOff, '${offline.map((d) => d.name).join(', ')} 응답 없음', '전원과 Wi-Fi 를 확인해 주세요');
  }
  return null;
}

/// 모든 화면 상단에 걸리는 한 줄 알림. 위험(빨강)만 채운 막대, 나머지는 흰 막대에 색 아이콘.
class StatusBanner extends StatelessWidget {
  const StatusBanner({super.key});

  @override
  Widget build(BuildContext context) {
    final state = context.select<HomeStore, HomeState>((s) => s.state);
    final elderly = context.elderly;
    return NowBuilder(
      builder: (context, now) {
        final b = bannerFor(state, now);
        if (b == null) return const SizedBox.shrink();
        final c = context.hv;
        final danger = b.tone == BannerTone.danger;
        final iconColor = switch (b.tone) {
          BannerTone.danger => Colors.white,
          BannerTone.warn => c.warn,
          BannerTone.caution => c.caution,
          BannerTone.muted => c.ink3,
        };
        final fs = elderly ? 18.0 : 15.0;
        return Padding(
          padding: const EdgeInsets.fromLTRB(32, 12, 32, 0),
          child: Container(
            constraints: BoxConstraints(minHeight: elderly ? 64 : 48),
            padding: const EdgeInsets.only(left: 16, right: 8),
            decoration: BoxDecoration(color: danger ? c.dangerFill : c.surface, borderRadius: BorderRadius.circular(12)),
            child: Row(
              children: [
                SoftPulse(active: danger, child: Icon(b.icon, size: elderly ? 24 : 20, color: iconColor)),
                const SizedBox(width: 12),
                Expanded(
                  child: Text.rich(
                    TextSpan(children: [
                      TextSpan(text: b.title, style: ts(fs, weight: w600, color: danger ? Colors.white : c.ink)),
                      TextSpan(
                          text: ' · ${b.detail}',
                          style: ts(fs, color: danger ? Colors.white.withValues(alpha: 0.85) : c.ink2, tabular: true)),
                    ]),
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                  ),
                ),
                if (b.actionLabel != null)
                  Pressable(
                    onTap: () {
                      if (b.openFall) context.read<HomeStore>().setFallAlert(true);
                      if (b.goTab != null) context.read<NavState>().go(b.goTab!);
                    },
                    child: ConstrainedBox(
                      constraints: const BoxConstraints(minHeight: 48, minWidth: 48),
                      child: Padding(
                        padding: const EdgeInsets.symmetric(horizontal: 8),
                        child: Row(
                          mainAxisSize: MainAxisSize.min,
                          children: [
                            Text(b.actionLabel!, style: ts(fs, weight: w600, color: danger ? Colors.white : c.brandInk)),
                            Icon(Ic.chevronRight, size: 16, color: danger ? Colors.white : c.brandInk),
                          ],
                        ),
                      ),
                    ),
                  ),
              ],
            ),
          ),
        );
      },
    );
  }
}
