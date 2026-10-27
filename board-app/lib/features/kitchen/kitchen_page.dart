import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../../app/canvas.dart';
import '../../app/page_header.dart';
import '../../models/types.dart';
import '../../store/home_state.dart';
import '../../store/home_store.dart';
import '../../theme/theme.dart';
import '../../ui/charts.dart';
import '../../ui/icons.dart';
import '../../ui/tile.dart';
import '../../ui/widgets.dart';
import '../../util/device_text.dart';
import '../../util/format.dart';
import '../../util/labels.dart';
import '../devices/device_widgets.dart';
import '../history/event_row.dart';
import '../history/session_timeline.dart';

const zoneLabel = {Zone.kitchen: '주방', Zone.near: '주방 근처', Zone.far: '멀리', Zone.unknown: '확인 중'};

/// 주방 (React KitchenPage)
class KitchenPage extends StatelessWidget {
  const KitchenPage({super.key});

  @override
  Widget build(BuildContext context) => context.elderly ? const _KitchenElderly() : const _KitchenNormal();
}

class _KitchenNormal extends StatefulWidget {
  const _KitchenNormal();
  @override
  State<_KitchenNormal> createState() => _KitchenNormalState();
}

enum _KTab { session, records }

class _KitchenNormalState extends State<_KitchenNormal> {
  // 같은 자리에서 '이번 조리' 와 '주방 기록' 을 바꿔 본다
  late _KTab _tab = context.read<HomeStore>().state.session != null ? _KTab.session : _KTab.records;

  @override
  Widget build(BuildContext context) {
    final c = context.hv;
    final short = MediaQuery.sizeOf(context).height <= 760;
    final state = context.select<HomeStore, HomeState>((s) => s.state);
    final induction = state.induction;
    final session = state.session;
    final others = state.devices.where((d) => d.room == RoomId.kitchen && d is! InductionDevice).toList();
    final recent = state.events.where((e) => e.room == RoomId.kitchen && e.type != SafetyEventType.cookingStarted).take(8).toList();
    final tileH = short ? 120.0 : 136.0;
    final tiles = <Widget>[_PresenceTile(p: state.kitchenPresence, location: state.location), for (final d in others) DeviceTile(device: d)];
    final slots = tiles.length.clamp(3, 4);

    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        const PageHeader(title: '주방'),
        Expanded(
          child: Padding(
            padding: EdgeInsets.fromLTRB(32, short ? 16 : 20, 32, short ? 20 : 28),
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                Expanded(
                  flex: 8,
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.stretch,
                    children: [
                      Expanded(child: induction != null ? _InductionPanel(device: induction) : const HvCard(child: SizedBox.expand())),
                      const SizedBox(height: 16),
                      SizedBox(
                        height: tileH,
                        child: Row(
                          crossAxisAlignment: CrossAxisAlignment.stretch,
                          children: [
                            // 재실 + 주방 기기(정수기 · 환풍기 · 조명 …). 3칸을 기본으로, 많으면 4칸까지
                            for (var i = 0; i < slots; i++) ...[
                              if (i > 0) const SizedBox(width: 12),
                              Expanded(child: i < tiles.length ? tiles[i] : const SizedBox.shrink()),
                            ],
                          ],
                        ),
                      ),
                    ],
                  ),
                ),
                SizedBox(width: short ? 16 : 24),
                Expanded(
                  flex: 4,
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.stretch,
                    children: [
                      Segmented<_KTab>(
                        value: _tab,
                        options: const [SegOption(_KTab.session, '이번 조리'), SegOption(_KTab.records, '주방 기록')],
                        onChanged: (v) => setState(() => _tab = v),
                      ),
                      const SizedBox(height: 16),
                      Expanded(
                        child: _tab == _KTab.session
                            ? (session != null
                                ? _SessionView(session: session)
                                : HvCard(
                                    child: Center(
                                      child: Column(
                                        mainAxisSize: MainAxisSize.min,
                                        children: [
                                          Icon(Ic.induction, size: 32, color: c.ink3),
                                          const SizedBox(height: 8),
                                          Text('조리 중 아님', style: ts(16, weight: w600, color: c.ink)),
                                          const SizedBox(height: 4),
                                          Text('인덕션을 켜면 흐름이 기록돼요', style: ts(14, color: c.ink3)),
                                        ],
                                      ),
                                    ),
                                  ))
                            : ListGroup(
                                expand: true,
                                children: [
                                  if (recent.isEmpty)
                                    Padding(
                                      padding: const EdgeInsets.all(16),
                                      child: Text('기록 없음', style: ts(15, color: c.ink3)),
                                    )
                                  else
                                    // 온전히 들어가는 줄만 (마지막 줄이 반쯤 잘리지 않게)
                                    Expanded(child: FitColumn(children: [for (final e in recent) EventRow(event: e, compact: true)])),
                                ],
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

class _SessionView extends StatelessWidget {
  const _SessionView({required this.session});
  final CookingSession session;

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        NowBuilder(
          builder: (context, now) => ListGroup(children: [
            ListRow(title: '시작', value: formatTime(session.startedAt)),
            ListRow(
              title: '진행',
              value: formatDuration(
                  now.difference(DateTime.tryParse(session.startedAt) ?? now).inMilliseconds / 1000),
            ),
            ListRow(title: '최고 온도', value: '${session.peakTemperature.round()}°C'),
          ]),
        ),
        const SizedBox(height: 20),
        Expanded(
          child: ListGroup(
            title: '흐름',
            expand: true,
            bodyPadding: const EdgeInsets.fromLTRB(16, 16, 16, 0),
            children: [
              Expanded(
                child: LayoutBuilder(builder: (context, box) {
                  // 칸 높이에 맞춰 최근 흐름만 (한 줄 약 34)
                  final max = (box.maxHeight / 34).floor().clamp(1, 6);
                  return ClipRect(
                    child: SingleChildScrollView(
                      physics: const NeverScrollableScrollPhysics(),
                      child: SessionTimeline(session: session, max: max),
                    ),
                  );
                }),
              ),
            ],
          ),
        ),
      ],
    );
  }
}

/// 인덕션 — 조회 전용. 큰 온도 숫자 + 최근 3분 그래프(과열 기준선)
class _InductionPanel extends StatelessWidget {
  const _InductionPanel({required this.device});
  final InductionDevice device;

  @override
  Widget build(BuildContext context) {
    final c = context.hv;
    final short = MediaQuery.sizeOf(context).height <= 760;
    final policy = context.select<HomeStore, KitchenPolicy>((s) => s.state.policy);
    final s = summarize(device);
    final b = device.burner;
    final hot = b.deviceState == BurnerState.overheated;
    final cooking = b.deviceState == BurnerState.on;
    return HvCard(
      color: hot ? c.dangerSoft : null,
      padding: const EdgeInsets.all(24),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Pressable(
            onTap: () => openDeviceSheet(context, device.id),
            semanticLabel: '인덕션 자세히',
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text('인덕션', style: ts(17, weight: w600, color: c.ink)),
                      Text(
                        '${device.online ? s.status : '응답 없음'}${cooking ? ' · ${formatDuration(b.activeSec)}째' : ''}',
                        style: ts(15, weight: hot ? w600 : w400, color: hot ? c.danger : c.ink2),
                      ),
                    ],
                  ),
                ),
                SizedBox(
                  height: 48,
                  child: Row(
                    mainAxisSize: MainAxisSize.min,
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Padding(padding: const EdgeInsets.only(top: 3), child: Icon(Ic.lock, size: 14, color: c.ink3)),
                      const SizedBox(width: 4),
                      Text('조회 전용', style: ts(13, color: c.ink3)),
                    ],
                  ),
                ),
              ],
            ),
          ),
          const SizedBox(height: 8),
          Expanded(
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.end,
              children: [
                Text.rich(
                  TextSpan(children: [
                    TextSpan(text: '${b.temperature.round()}'),
                    WidgetSpan(
                      alignment: PlaceholderAlignment.top,
                      child: Text('°C', style: ts(32, weight: w300, color: c.ink3, height: 1.2)),
                    ),
                  ]),
                  style: ts(short ? 64 : 80, weight: w200, color: hot ? c.danger : (cooking ? c.ink : c.ink2), height: 0.9, tracking: -0.04, tabular: true),
                ),
                const SizedBox(width: 32),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.stretch,
                    children: [
                      Text('과열 ${policy.overheatEnterC.round()}°', textAlign: TextAlign.right, style: ts(12, color: c.danger)),
                      const SizedBox(height: 4),
                      Expanded(
                        child: Semantics(
                          label: '최근 3분 온도 추이',
                          child: Sparkline(
                            values: device.tempHistory,
                            max: policy.overheatEnterC + 15 > 170 ? policy.overheatEnterC + 15 : 170,
                            threshold: policy.overheatEnterC,
                            thresholdColor: c.danger,
                            color: hot ? c.danger : c.glyphHeat,
                          ),
                        ),
                      ),
                      const SizedBox(height: 4),
                      Row(
                        mainAxisAlignment: MainAxisAlignment.spaceBetween,
                        children: [Text('3분 전', style: ts(12, color: c.ink3)), Text('지금', style: ts(12, color: c.ink3))],
                      ),
                    ],
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

class _PresenceTile extends StatelessWidget {
  const _PresenceTile({required this.p, required this.location});
  final Presence p;
  final Location location;

  @override
  Widget build(BuildContext context) {
    final c = context.hv;
    final here = p.present;
    final state = here
        ? '사람 있음 · ${(p.confidence * 100).round()}%'
        : '${formatDuration(p.absentSec)} 비어 있음 · ${p.zone == Zone.unknown ? locationLabel[location] : zoneLabel[p.zone]}';
    return Tile(icon: Ic.radar, glyph: c.brandInk, name: '재실 감지', state: state, on: here);
  }
}

// ── 어르신 모드 ───────────────────────────────────────────────────────────
class _KitchenElderly extends StatelessWidget {
  const _KitchenElderly();

  @override
  Widget build(BuildContext context) {
    final c = context.hv;
    final state = context.select<HomeStore, HomeState>((s) => s.state);
    final induction = state.induction;
    final line = describeKitchen(state.kitchenPhase, induction, state.kitchenPresence);
    final b = induction?.burner;
    final hot = b?.deviceState == BurnerState.overheated;
    final here = state.kitchenPresence.present;
    final lights = state.devices.whereType<LightDevice>().where((d) => d.room == RoomId.kitchen).take(2).toList();
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        const PageHeader(title: '주방'),
        Expanded(
          child: Padding(
            padding: const EdgeInsets.fromLTRB(32, 20, 32, 28),
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                Expanded(
                  child: Tile(
                    big: true,
                    icon: Ic.induction,
                    glyph: c.glyphHeat,
                    name: '인덕션',
                    state: line.short,
                    on: b?.deviceState == BurnerState.on,
                    tone: hot ? TileTone.danger : (line.risk == Risk.warning || line.risk == Risk.caution ? TileTone.warn : null),
                    value: b != null ? '${b.temperature.round()}°' : null,
                  ),
                ),
                const SizedBox(width: 16),
                Expanded(
                  child: Tile(
                    big: true,
                    icon: Ic.radar,
                    glyph: c.brandInk,
                    name: '주방에',
                    on: here,
                    tone: here ? null : (line.risk != Risk.normal ? TileTone.warn : null),
                    state: here ? '사람이 있어요' : '아무도 없어요 · ${formatDuration(state.kitchenPresence.absentSec)}',
                  ),
                ),
                // 주방 조명 (백엔드 v0.8 light-02 등 — 공간이 주방인 전등이면 모두). 누르면 켜고 끈다
                for (final l in lights) ...[
                  const SizedBox(width: 16),
                  Expanded(child: DeviceTile(device: l, big: true)),
                ],
              ],
            ),
          ),
        ),
      ],
    );
  }
}
