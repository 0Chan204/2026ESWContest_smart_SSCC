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
import '../../util/format.dart';
import '../../util/labels.dart';
import '../devices/device_widgets.dart';
import '../history/event_row.dart';

/// 욕실 (React BathroomPage): 상태 패널 · 조명/재실/환풍기 타일 · 낙상 대응 단계 · 욕실 기록
class BathroomPage extends StatelessWidget {
  const BathroomPage({super.key});

  @override
  Widget build(BuildContext context) {
    final c = context.hv;
    final elderly = context.elderly;
    final short = MediaQuery.sizeOf(context).height <= 760;
    final state = context.select<HomeStore, HomeState>((s) => s.state);
    final fall = state.fall;
    final p = state.bathroomPresence;
    final pending = fall?.status == FallStatus.pending;
    final bathDevices = state.devices.where((d) => d.room == RoomId.bathroom).toList();
    final recent = state.events.where((e) => e.room == RoomId.bathroom).take(8).toList();
    SafetyEvent? lastFall;
    for (final e in state.events) {
      if (e.type == SafetyEventType.fallDetected) {
        lastFall = e;
        break;
      }
    }
    final guardian = state.contacts.guardian;
    final tileH = elderly ? 160.0 : (short ? 132.0 : 156.0);

    final tiles = <Widget>[
      for (final d in bathDevices) Expanded(child: DeviceTile(device: d, big: elderly)),
      Expanded(
        child: Tile(
          big: elderly,
          icon: Ic.radar,
          glyph: c.brandInk,
          name: '재실 감지',
          on: p.present,
          state: p.present ? '사람 있음' : '비어 있음${p.absentSec > 0 ? ' · ${formatDuration(p.absentSec)}' : ''}',
        ),
      ),
      if (!elderly)
        Expanded(
          flex: 2,
          child: Container(
            clipBehavior: Clip.antiAlias,
            decoration: BoxDecoration(color: c.surface, borderRadius: BorderRadius.circular(12)),
            child: const Column(
              children: [
                _Stage(first: true, t: '5초', d: '누운 뒤 움직임 없음 → 낙상 확인'),
                _Stage(t: '10초', d: '화면·음성 경고, 보호자 문자'),
                _Stage(t: '30초', d: '응답 없으면 자동 신고'),
              ],
            ),
          ),
        ),
    ];

    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        const PageHeader(title: '욕실'),
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
                      Expanded(
                        child: NowBuilder(
                          builder: (context, now) => _StatusPanel(
                            fall: fall,
                            presence: p,
                            pending: pending,
                            lastFall: lastFall,
                            guardian: guardian,
                            now: now,
                          ),
                        ),
                      ),
                      const SizedBox(height: 16),
                      SizedBox(
                        height: tileH,
                        child: Row(
                          crossAxisAlignment: CrossAxisAlignment.stretch,
                          children: [
                            for (var i = 0; i < tiles.length; i++) ...[if (i > 0) const SizedBox(width: 12), tiles[i]],
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
                      const SectionTitle(title: '욕실 기록'),
                      Expanded(
                        child: ListGroup(
                          expand: true,
                          children: [
                            if (recent.isEmpty)
                              Padding(padding: const EdgeInsets.all(16), child: Text('기록 없음', style: ts(15, color: c.ink3)))
                            else
                              Expanded(child: FitColumn(children: [for (final e in recent) EventRow(event: e, compact: true, big: elderly)])),
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

class _StatusPanel extends StatelessWidget {
  const _StatusPanel({
    required this.fall,
    required this.presence,
    required this.pending,
    required this.lastFall,
    required this.guardian,
    required this.now,
  });
  final FallIncident? fall;
  final Presence presence;
  final bool pending;
  final SafetyEvent? lastFall;
  final Contact? guardian;
  final DateTime now;

  @override
  Widget build(BuildContext context) {
    final c = context.hv;
    final elderly = context.elderly;
    final p = presence;
    final icon = pending ? Ic.alert : (p.present ? Ic.user : Ic.personStanding);
    final title = pending ? '낙상 감지' : (p.present ? '사용 중' : '비어 있음');
    final f = fall;
    final detail = pending
        ? '보호자 응답이 없으면 ${formatCountdown(secondsUntil(f!.autoReportAt, now))} 후 자동 신고'
        : f != null
            ? '최근 낙상 · ${fallStatusLabel[f.status]}'
            : p.present
                ? '움직임 정상 · ${formatAgo(p.observedAt, now)} 확인'
                : '들어오면 조명이 자동으로 켜져요';

    return HvCard(
      color: pending ? c.dangerSoft : null,
      padding: const EdgeInsets.all(28),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              mainAxisAlignment: MainAxisAlignment.spaceBetween,
              children: [
                SoftPulse(
                  active: pending,
                  child: Icon(icon, size: elderly ? 56 : 44, color: pending ? c.danger : (p.present ? c.brandInk : c.ink3)),
                ),
                Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    Text(title,
                        style: ts(elderly ? 52 : 44, weight: w700, color: pending ? c.danger : c.ink, height: 1.25, tracking: -0.02)),
                    const SizedBox(height: 4),
                    Text(detail,
                        style: ts(elderly ? 24 : 17, weight: pending ? w600 : w400, color: pending ? c.danger : c.ink2, tabular: true),
                        maxLines: 2,
                        overflow: TextOverflow.ellipsis),
                    if (pending)
                      Padding(
                        padding: const EdgeInsets.only(top: 20),
                        child: HvButton(
                          label: '자세히 보기',
                          variant: BtnVariant.danger,
                          size: elderly ? BtnSize.xl : BtnSize.lg,
                          onPressed: () => context.read<HomeStore>().setFallAlert(true),
                        ),
                      ),
                  ],
                ),
              ],
            ),
          ),
          if (!elderly && !pending) ...[
            const SizedBox(width: 24),
            SizedBox(
              width: 288,
              child: Column(
                mainAxisAlignment: MainAxisAlignment.end,
                children: [
                  _Info(first: true, k: '감지', v: '${p.present ? '사람 있음' : '비어 있음'} · ${(p.confidence * 100).round()}%'),
                  _Info(k: '최근 낙상', v: lastFall != null ? formatWhen(lastFall!.occurredAt, now) : '없음'),
                  _Info(k: '보호자 알림', v: guardian?.name ?? '미등록', warn: guardian == null),
                ],
              ),
            ),
          ],
        ],
      ),
    );
  }
}

class _Info extends StatelessWidget {
  const _Info({required this.k, required this.v, this.warn = false, this.first = false});
  final String k;
  final String v;
  final bool warn;
  final bool first;

  @override
  Widget build(BuildContext context) {
    final c = context.hv;
    return Container(
      decoration: BoxDecoration(border: first ? null : Border(top: BorderSide(color: c.line))),
      padding: const EdgeInsets.symmetric(vertical: 10),
      child: Row(
        children: [
          Text(k, style: ts(15, color: c.ink2)),
          const SizedBox(width: 12),
          Expanded(
            child: Text(v,
                textAlign: TextAlign.right,
                style: ts(15, weight: w500, color: warn ? c.warn : c.ink),
                maxLines: 1,
                overflow: TextOverflow.ellipsis),
          ),
        ],
      ),
    );
  }
}

/// 낙상 대응 단계 한 줄
class _Stage extends StatelessWidget {
  const _Stage({required this.t, required this.d, this.first = false});
  final String t;
  final String d;
  final bool first;

  @override
  Widget build(BuildContext context) {
    final c = context.hv;
    return Expanded(
      child: Padding(
        padding: const EdgeInsets.only(left: 16),
        child: Row(
          children: [
            SizedBox(width: 40, child: Text(t, style: ts(15, weight: w600, color: c.ink, tabular: true))),
            const SizedBox(width: 12),
            Expanded(
              child: Container(
                height: double.infinity,
                alignment: Alignment.centerLeft,
                padding: const EdgeInsets.only(right: 16),
                decoration: BoxDecoration(border: first ? null : Border(top: BorderSide(color: c.line))),
                child: Text(d, style: ts(14, color: c.ink2), maxLines: 1, overflow: TextOverflow.ellipsis),
              ),
            ),
          ],
        ),
      ),
    );
  }
}
