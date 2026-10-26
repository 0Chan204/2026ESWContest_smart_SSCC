import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../../app/app.dart';
import '../../app/page_header.dart';
import '../../models/types.dart';
import '../../store/home_state.dart';
import '../../store/home_store.dart';
import '../../theme/theme.dart';
import '../../ui/icons.dart';
import '../../ui/sheet.dart';
import '../../ui/tile.dart';
import '../../ui/widgets.dart';
import '../../util/device_text.dart';
import '../../util/labels.dart';
import '../devices/device_widgets.dart';
import 'home_map.dart';
import 'location_sheet.dart';

/// 홈 (React HomePage). 일반 = 집 상태 | 위치 평면도 + 기기 카드 한 줄, 어르신 = 상태 한 줄 + 큰 타일 네 개
class HomePage extends StatelessWidget {
  const HomePage({super.key});

  @override
  Widget build(BuildContext context) => context.elderly ? const _HomeElderly() : const _HomeNormal();
}

void openLocationSheet(BuildContext context) => showSheet(context, (_) => const LocationSheet());

TileTone? _riskTone(Risk r) => switch (r) {
      Risk.danger => TileTone.danger,
      Risk.warning || Risk.caution => TileTone.warn,
      Risk.uncertain => TileTone.muted,
      Risk.normal => null,
    };

bool _short(BuildContext context) => MediaQuery.sizeOf(context).height <= 760;

// ── 일반 모드 ───────────────────────────────────────────────────────────────
class _HomeNormal extends StatelessWidget {
  const _HomeNormal();

  @override
  Widget build(BuildContext context) {
    final short = _short(context);
    final state = context.select<HomeStore, HomeState>((s) => s.state);
    // 조명은 평면도에서 조작하므로 기기 줄에는 인덕션 · 정수기 · 환풍기 · 공기청정기만
    final devices = state.devices.where((d) => d is! LightDevice).toList();
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        const PageHeader(title: '우리 집'),
        Expanded(
          child: Padding(
            padding: EdgeInsets.fromLTRB(32, short ? 16 : 20, 32, short ? 20 : 28),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                const Expanded(
                  child: Row(
                    crossAxisAlignment: CrossAxisAlignment.stretch,
                    children: [
                      Expanded(flex: 7, child: _StatusCard()),
                      SizedBox(width: 20),
                      Expanded(flex: 5, child: _LocationCard()),
                    ],
                  ),
                ),
                SizedBox(height: short ? 16 : 24),
                SectionTitle(title: '기기', count: '${devices.length}', action: const _RefreshButton()),
                SizedBox(
                  height: short ? 144 : 158,
                  child: Row(
                    crossAxisAlignment: CrossAxisAlignment.stretch,
                    children: [
                      for (var i = 0; i < devices.length && i < 5; i++) ...[
                        if (i > 0) const SizedBox(width: 14),
                        Expanded(child: DeviceCard(device: devices[i])),
                      ],
                    ],
                  ),
                ),
              ],
            ),
          ),
        ),
      ],
    );
  }
}

/// 집 상태 카드: 전체 위험 + 주방 · 욕실 · 보호자 줄
class _StatusCard extends StatelessWidget {
  const _StatusCard();

  @override
  Widget build(BuildContext context) {
    final c = context.hv;
    final short = _short(context);
    final state = context.select<HomeStore, HomeState>((s) => s.state);
    final risk = state.overallRisk;
    final k = describeKitchen(state.kitchenPhase, state.induction, state.kitchenPresence);
    final b = describeBathroom(state.fall, state.bathroomPresence);
    final guardian = state.contacts.guardian;
    final nav = context.read<NavState>();
    final bg = switch (risk) {
      Risk.caution => c.cautionSoft,
      Risk.warning => c.warnSoft,
      Risk.danger => c.dangerSoft,
      _ => c.surface,
    };
    return HvCard(
      color: bg,
      padding: EdgeInsets.all(short ? 20 : 24),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        mainAxisAlignment: MainAxisAlignment.spaceBetween,
        children: [
          Row(
            children: [
              Icon(risk == Risk.normal ? Ic.shieldCheck : Ic.shieldAlert, size: 32, color: c.riskText(risk)),
              const SizedBox(width: 12),
              Expanded(
                child: Text(heroTitle[risk]!,
                    style: ts(28, weight: w700, color: c.ink, height: 1.25, tracking: -0.01), maxLines: 1, overflow: TextOverflow.ellipsis),
              ),
            ],
          ),
          const SizedBox(height: 12),
          Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              _StatusRow(first: true, icon: Ic.kitchen, name: '주방', value: k.short, risk: k.risk, onTap: () => nav.go(AppTab.kitchen)),
              _StatusRow(icon: Ic.bath, name: '욕실', value: b.short, risk: b.risk, onTap: () => nav.go(AppTab.bathroom)),
              _StatusRow(
                icon: Ic.phone,
                name: '보호자',
                value: guardian?.name ?? '등록 필요',
                risk: guardian != null ? Risk.normal : Risk.warning,
                neutral: guardian != null,
                onTap: () => nav.go(AppTab.settings, section: 'contacts'),
              ),
            ],
          ),
        ],
      ),
    );
  }
}

class _StatusRow extends StatelessWidget {
  const _StatusRow({
    required this.icon,
    required this.name,
    required this.value,
    required this.risk,
    required this.onTap,
    this.neutral = false,
    this.first = false,
  });
  final IconData icon;
  final String name;
  final String value;
  final Risk risk;
  final bool neutral;
  final bool first;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final c = context.hv;
    final short = _short(context);
    return Pressable(
      onTap: onTap,
      semanticLabel: '$name $value',
      child: Row(
        children: [
          Icon(icon, size: 20, color: c.ink3),
          const SizedBox(width: 12),
          Expanded(
            child: Container(
              constraints: BoxConstraints(minHeight: short ? 48 : 52),
              decoration: BoxDecoration(border: first ? null : Border(top: BorderSide(color: c.line))),
              child: Row(
                children: [
                  SizedBox(width: 64, child: Text(name, style: ts(17, weight: w600, color: c.ink), maxLines: 1)),
                  const SizedBox(width: 12),
                  Expanded(
                    child: Text(value,
                        style: ts(16, weight: w500, color: neutral ? c.ink2 : c.riskText(risk)),
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis),
                  ),
                  Icon(Ic.chevronRight, size: 16, color: c.ink3),
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }
}

/// 위치 + 조명: 평면도의 전구를 눌러 켜고 끈다. 밝기 · 환풍기는 '크게 보기'에서
class _LocationCard extends StatelessWidget {
  const _LocationCard();

  @override
  Widget build(BuildContext context) {
    final c = context.hv;
    final short = _short(context);
    final location = context.select<HomeStore, Location>((s) => s.state.location);
    return HvCard(
      padding: EdgeInsets.all(short ? 16 : 20),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          SizedBox(
            height: 40,
            child: Row(
              children: [
                Expanded(
                  child: Text.rich(
                    TextSpan(children: [
                      const TextSpan(text: '지금 위치 '),
                      TextSpan(text: locationLabel[location], style: TextStyle(color: c.brandInk)),
                    ]),
                    style: ts(17, weight: w600, color: c.ink),
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                  ),
                ),
                Transform.translate(
                  offset: const Offset(8, 0),
                  child: Pressable(
                    onTap: () => openLocationSheet(context),
                    semanticLabel: '위치 크게 보기',
                    child: Container(
                      constraints: const BoxConstraints(minHeight: 48),
                      padding: const EdgeInsets.symmetric(horizontal: 8),
                      child: Row(
                        mainAxisSize: MainAxisSize.min,
                        children: [
                          Icon(Ic.maximize, size: 16, color: c.brandInk),
                          const SizedBox(width: 6),
                          Text('크게 보기', style: ts(15, weight: w600, color: c.brandInk)),
                        ],
                      ),
                    ),
                  ),
                ),
              ],
            ),
          ),
          const SizedBox(height: 12),
          const Expanded(child: HomeMap()),
        ],
      ),
    );
  }
}

/// 다시 확인 (기기 상태를 서버에서 다시 받는다)
class _RefreshButton extends StatefulWidget {
  const _RefreshButton();
  @override
  State<_RefreshButton> createState() => _RefreshButtonState();
}

class _RefreshButtonState extends State<_RefreshButton> {
  bool _busy = false;

  Future<void> _run() async {
    setState(() => _busy = true);
    try {
      await context.read<HomeStore>().refresh();
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final c = context.hv;
    return Opacity(
      opacity: _busy ? 0.6 : 1,
      child: Pressable(
        onTap: _busy ? null : _run,
        child: SizedBox(
          height: 32,
          child: Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              SpinningIcon(icon: Ic.refresh, size: 16, color: c.brandInk, spinning: _busy),
              const SizedBox(width: 6),
              Text(_busy ? '확인 중…' : '다시 확인', style: ts(15, color: c.brandInk)),
            ],
          ),
        ),
      ),
    );
  }
}

// ── 어르신 모드: 상태 한 줄 + 큰 타일 네 개 ───────────────────────────────────
class _HomeElderly extends StatelessWidget {
  const _HomeElderly();

  @override
  Widget build(BuildContext context) {
    final c = context.hv;
    final state = context.select<HomeStore, HomeState>((s) => s.state);
    final risk = state.overallRisk;
    final k = describeKitchen(state.kitchenPhase, state.induction, state.kitchenPresence);
    final b = describeBathroom(state.fall, state.bathroomPresence);
    final guardian = state.contacts.guardian;
    final nav = context.read<NavState>();
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        const PageHeader(title: '우리 집'),
        Padding(
          padding: const EdgeInsets.fromLTRB(32, 16, 32, 0),
          child: Row(
            children: [
              Icon(risk == Risk.normal ? Ic.shieldCheck : Ic.shieldAlert, size: 36, color: c.riskText(risk)),
              const SizedBox(width: 12),
              Expanded(
                child: Text(heroTitle[risk]!, style: ts(28, weight: w700, color: c.ink), maxLines: 1, overflow: TextOverflow.ellipsis),
              ),
            ],
          ),
        ),
        Expanded(
          child: Padding(
            padding: const EdgeInsets.fromLTRB(32, 16, 32, 28),
            child: Column(
              children: [
                Expanded(
                  child: Row(
                    crossAxisAlignment: CrossAxisAlignment.stretch,
                    children: [
                      Expanded(
                        child: Tile(
                          big: true,
                          icon: Ic.kitchen,
                          glyph: c.glyphHeat,
                          name: '주방',
                          state: k.short,
                          on: k.risk == Risk.normal,
                          tone: _riskTone(k.risk),
                          onPress: () => nav.go(AppTab.kitchen),
                        ),
                      ),
                      const SizedBox(width: 16),
                      Expanded(
                        child: Tile(
                          big: true,
                          icon: Ic.bath,
                          glyph: c.glyphWater,
                          name: '욕실',
                          state: b.short,
                          on: b.risk == Risk.normal,
                          tone: _riskTone(b.risk),
                          onPress: () => nav.go(AppTab.bathroom),
                        ),
                      ),
                    ],
                  ),
                ),
                const SizedBox(height: 16),
                Expanded(
                  child: Row(
                    crossAxisAlignment: CrossAxisAlignment.stretch,
                    children: [
                      Expanded(
                        child: Tile(
                          big: true,
                          icon: Ic.mapPin,
                          glyph: c.brandInk,
                          name: '지금 위치',
                          state: locationLabel[state.location]!,
                          on: true,
                          onPress: () => openLocationSheet(context),
                        ),
                      ),
                      const SizedBox(width: 16),
                      Expanded(
                        child: Tile(
                          big: true,
                          icon: Ic.phone,
                          glyph: c.ok,
                          name: '보호자',
                          state: guardian?.name ?? '등록해 주세요',
                          on: guardian != null,
                          tone: guardian != null ? null : TileTone.warn,
                          onPress: () => nav.go(AppTab.settings, section: 'contacts'),
                        ),
                      ),
                    ],
                  ),
                ),
              ],
            ),
          ),
        ),
      ],
    );
  }
}
