import 'dart:async';
import 'dart:math' as math;

import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../../app/canvas.dart';
import '../../models/types.dart';
import '../../store/home_state.dart';
import '../../store/home_store.dart';
import '../../store/preferences.dart';
import '../../theme/theme.dart';
import '../../ui/charts.dart';
import '../../ui/icons.dart';
import '../../ui/sheet.dart';
import '../../ui/widgets.dart';
import '../../util/device_text.dart';
import '../../util/format.dart';
import '../../util/labels.dart';
import 'home_map.dart';
import 'room_controls.dart';

/// 센서 노드 신호를 묻는 주기 (열려 있는 동안만)
const nodePoll = Duration(milliseconds: 2500);

/// 위치 크게 보기 = 재실 감지 화면 (React LocationSheet).
/// 공간마다 한 칸: 재실 판단(신뢰도 · 행동 · 최근 1분 그래프 · 센서 노드 신호) + 그 공간의 조명 · 환풍기 · 공기청정기.
/// 재실 판단 결과는 사람이 있는 공간 하나만 알려주므로, 신뢰도 숫자는 그 공간에만 보여준다.
class LocationSheet extends StatefulWidget {
  const LocationSheet({super.key});

  @override
  State<LocationSheet> createState() => _LocationSheetState();
}

class _LocationSheetState extends State<LocationSheet> {
  /// null = 아직 불러오는 중
  List<SensingNode>? _nodes;
  Timer? _timer;
  bool _alive = true;

  @override
  void initState() {
    super.initState();
    _load();
    _timer = Timer.periodic(nodePoll, (_) => _load());
  }

  Future<void> _load() async {
    // 어르신 모드는 센서 신호 줄을 보여주지 않는다
    if (context.read<Preferences>().elderly) return;
    final store = context.read<HomeStore>();
    try {
      final n = await store.source.loadSensingNodes();
      if (_alive && mounted) setState(() => _nodes = n);
    } catch (_) {
      if (_alive && mounted) setState(() => _nodes = const []);
    }
  }

  @override
  void dispose() {
    _alive = false;
    _timer?.cancel();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final c = context.hv;
    final elderly = context.elderly;
    final state = context.select<HomeStore, HomeState>((s) => s.state);
    final rooms = roomsOf(state);
    final latest = state.latestSensing;
    final location = state.location;
    final where = location == Location.outside
        ? '집 밖에 계세요'
        : location == Location.unknown
            ? '위치 확인 중'
            : '${locationLabel[location]}에 계세요';
    void close() => Navigator.of(context).maybePop();

    return NowBuilder(
      builder: (context, now) {
        final live = isFresh(latest, now);
        return SheetFrame(
          onClose: close,
          width: elderly ? 980 : 1000,
          title: '지금 위치',
          scrollable: false,
          subtitle: Wrap(
            crossAxisAlignment: WrapCrossAlignment.center,
            spacing: 8,
            children: [
              Text(where),
              Text('·', style: TextStyle(color: c.ink3)),
              if (latest != null)
                Row(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    Container(
                      width: 8,
                      height: 8,
                      decoration: BoxDecoration(color: live ? c.ok : c.warn, shape: BoxShape.circle),
                    ),
                    const SizedBox(width: 6),
                    Text(live ? '실시간' : '갱신 멈춤', style: TextStyle(color: live ? c.ok : c.warn)),
                    const SizedBox(width: 6),
                    Text(agoShort(latest.at, now), style: ts(14, color: c.ink3, tabular: true)),
                  ],
                )
              else
                Text('재실 판단 결과 없음', style: TextStyle(color: c.ink3)),
            ],
          ),
          child: LayoutBuilder(builder: (context, box) {
            final short = MediaQuery.sizeOf(context).height <= 760;
            final showNote = !(elderly && short);
            final noteH = showNote ? 28.0 : 0.0;
            final maxH = box.maxHeight.isFinite ? box.maxHeight : 560.0;
            final h = math.max(240.0, math.min(maxH - noteH, elderly ? 520.0 : 540.0));
            return Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                SizedBox(
                  height: h,
                  child: Container(
                    padding: const EdgeInsets.all(2),
                    clipBehavior: Clip.antiAlias,
                    decoration: BoxDecoration(color: c.line, borderRadius: BorderRadius.circular(12)),
                    child: Row(
                      crossAxisAlignment: CrossAxisAlignment.stretch,
                      children: [
                        for (var i = 0; i < rooms.length; i++) ...[
                          if (i > 0) const SizedBox(width: 2),
                          Expanded(
                            child: _RoomColumn(
                              room: rooms[i],
                              latest: latest,
                              history: state.sensing,
                              now: now,
                              node: _nodeFor(rooms[i].id),
                              loadingNode: _nodes == null,
                              radius: switch (i) {
                                0 => const BorderRadius.horizontal(left: Radius.circular(10)),
                                2 => const BorderRadius.horizontal(right: Radius.circular(10)),
                                _ => BorderRadius.zero,
                              },
                            ),
                          ),
                        ],
                      ],
                    ),
                  ),
                ),
                if (showNote)
                  Padding(
                    padding: const EdgeInsets.fromLTRB(16, 8, 16, 0),
                    child: Text('각 공간의 Wi-Fi 신호로 판단해요. 카메라는 쓰지 않아요.', style: ts(13, color: c.ink3), maxLines: 1),
                  ),
              ],
            );
          }),
        );
      },
    );
  }

  SensingNode? _nodeFor(HouseRoom room) {
    final n = _nodes;
    if (n == null) return null;
    for (final x in n) {
      if (x.room == room) return x;
    }
    return null;
  }
}

class _RoomColumn extends StatelessWidget {
  const _RoomColumn({
    required this.room,
    required this.latest,
    required this.history,
    required this.now,
    required this.node,
    required this.loadingNode,
    required this.radius,
  });

  final RoomInfo room;
  final SensingSample? latest;
  final List<SensingSample> history;
  final DateTime now;
  final SensingNode? node;
  final bool loadingNode;
  final BorderRadius radius;

  @override
  Widget build(BuildContext context) {
    final c = context.hv;
    final elderly = context.elderly;
    final short = MediaQuery.sizeOf(context).height <= 760;
    final r = room;
    final rInk = riskInk(r.risk, c);
    final rBg = riskBg(r.risk, c);
    final p = roomPresence(latest, r.id, now);
    final live = p.freshness == Freshness.live;
    final series = roomSeries(history, r.id, now);
    // 비어 있으면 최근 1분 안에 마지막으로 있었던 때
    SensingSample? lastSeen;
    for (final s in history.reversed) {
      final t = DateTime.tryParse(s.at);
      if (s.present && s.room == r.id && t != null && now.difference(t) <= sensingWindow) {
        lastSeen = s;
        break;
      }
    }
    final l = latest;
    final big = l == null
        ? '결과 없음'
        : !live
            ? '확인 중'
            : p.present
                ? (p.percent != null ? '${p.percent}%' : '있음')
                : '비어 있음';
    final numeric = live && p.present && p.percent != null;
    final line = l == null
        ? '재실 판단을 기다리는 중'
        : !live
            ? '${agoShort(l.at, now)} 결과'
            : p.present
                ? ['사람 있음', if (p.activity != null) p.activity!].join(' · ')
                : lastSeen != null
                    ? '${agoShort(lastSeen.at, now)}까지 있었어요'
                    : '최근 1분 감지 없음';
    final bigColor = p.present && live ? (rInk ?? c.ink) : c.ink3;
    final sparkColor = rInk != null ? c.danger : (series.any((v) => v > 0) ? c.brandInk : c.ink3);

    final info = Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      mainAxisSize: MainAxisSize.min,
      children: [
        SizedBox(
          height: 40,
          child: Row(
            children: [
              Expanded(
                child: Text(houseRoomLabel[r.id]!,
                    style: ts(elderly ? 22 : 17, weight: w600, color: rInk ?? (r.here ? c.brandInk : c.ink2)), maxLines: 1),
              ),
              if (r.here)
                Semantics(
                  label: '지금 여기 계세요',
                  child: LocateDot(size: 40, color: c.brand, child: const Icon(Ic.user, size: 20, color: Colors.white)),
                ),
            ],
          ),
        ),
        const SizedBox(height: 4),
        SizedBox(
          height: elderly ? 48 : 56,
          child: Align(
            alignment: Alignment.bottomLeft,
            child: FittedBox(
              fit: BoxFit.scaleDown,
              alignment: Alignment.bottomLeft,
              child: Text(
                big,
                style: numeric
                    ? ts(elderly ? 44 : 52, weight: w300, color: bigColor, height: 1, tracking: -0.03, tabular: true)
                    : ts(elderly ? 28 : 26, weight: w600, color: bigColor, height: 1),
              ),
            ),
          ),
        ),
        const SizedBox(height: 6),
        Text(line,
            style: ts(elderly ? 18 : 15, weight: p.present && live ? w500 : w400, color: p.present && live ? c.ink : c.ink2),
            maxLines: 1,
            overflow: TextOverflow.ellipsis),
        if (!elderly) ...[
          const SizedBox(height: 12),
          SizedBox(
            height: 44,
            child: Semantics(
              label: '${houseRoomLabel[r.id]} 최근 1분 재실 신뢰도',
              child: Sparkline(values: series.isNotEmpty ? series : const [0, 0], min: 0, max: 100, color: sparkColor),
            ),
          ),
          const SizedBox(height: 8),
          _NodeLine(node: node, loading: loadingNode),
        ],
      ],
    );

    return Container(
      decoration: BoxDecoration(color: rBg ?? (r.here ? c.brandSoft : c.surface), borderRadius: radius),
      padding: EdgeInsets.all(elderly && short ? 12 : 16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          // 내용이 길면 칸 안에서만 밀려 올라가게 (넘침 대신)
          Expanded(child: SingleChildScrollView(physics: const ClampingScrollPhysics(), child: info)),
          const SizedBox(height: 12),
          RoomControls(lights: r.lights, fans: r.fans, airs: r.airs),
        ],
      ),
    );
  }
}

/// 센서 노드 한 줄: 이름 · 신호 막대 · dBm · Hz · 상태
class _NodeLine extends StatelessWidget {
  const _NodeLine({required this.node, required this.loading});
  final SensingNode? node;
  final bool loading;

  @override
  Widget build(BuildContext context) {
    final c = context.hv;
    final n = node;
    if (n == null) {
      return SizedBox(height: 20, child: Text(loading ? '센서 신호 확인 중' : '센서 정보 없음', style: ts(13, color: c.ink3)));
    }
    final ok = n.status == NodeStatus.ok;
    final bars = rssiBars(n.rssi);
    return SizedBox(
      height: 20,
      child: Row(
        children: [
          Text(n.node.toUpperCase(), style: ts(13, weight: w600, color: c.ink2)),
          if (ok) ...[
            const SizedBox(width: 8),
            Semantics(
              label: '신호 $bars단계',
              child: SizedBox(
                height: 12,
                child: Row(
                  crossAxisAlignment: CrossAxisAlignment.end,
                  children: [
                    for (var i = 1; i <= 4; i++)
                      Container(
                        width: 3,
                        height: 12 * i / 4,
                        margin: const EdgeInsets.only(right: 2),
                        decoration: BoxDecoration(color: i <= bars ? c.ink2 : c.track, borderRadius: BorderRadius.circular(1)),
                      ),
                  ],
                ),
              ),
            ),
            const SizedBox(width: 6),
            Expanded(
              child: Text(
                '${n.rssi != null ? '${n.rssi!.round()} dBm' : '–'} · ${n.rateHz != null ? '${n.rateHz!.toStringAsFixed(1)} Hz' : '–'}',
                style: ts(13, color: c.ink2, tabular: true),
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
              ),
            ),
          ] else
            const Spacer(),
          const SizedBox(width: 8),
          Text(nodeStatusLabel[n.status]!, style: ts(13, weight: w500, color: ok ? c.ok : c.warn)),
        ],
      ),
    );
  }
}
