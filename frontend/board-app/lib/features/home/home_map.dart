import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../../app/canvas.dart';
import '../../models/types.dart';
import '../../store/home_state.dart';
import '../../store/home_store.dart';
import '../../theme/theme.dart';
import '../../theme/tokens.dart';
import '../../ui/icons.dart';
import '../../ui/widgets.dart';
import '../../util/device_text.dart';
import '../../util/labels.dart';

/// 평면도 · 재실 감지 화면이 같이 쓰는 공간 정보 (주방 | 침실 | 욕실)
class RoomInfo {
  const RoomInfo(this.id, this.risk, this.here, this.lights, this.fans, this.airs);
  final HouseRoom id;
  final Risk risk;
  final bool here;
  final List<LightDevice> lights;
  final List<FanDevice> fans;
  final List<AirPurifierDevice> airs;
}

List<RoomInfo> roomsOf(HomeState s) {
  final risk = {HouseRoom.kitchen: s.kitchenRisk, HouseRoom.bedroom: Risk.normal, HouseRoom.bathroom: s.bathroomRisk};
  return [
    for (final id in houseRooms)
      RoomInfo(
        id,
        risk[id]!,
        s.location == id.location,
        s.devices.whereType<LightDevice>().where((d) => d.room == id.roomId).toList(),
        s.devices.whereType<FanDevice>().where((d) => d.room == id.roomId).toList(),
        s.devices.whereType<AirPurifierDevice>().where((d) => d.room == id.roomId).toList(),
      ),
  ];
}

/// 위험한 방 바탕 · 글자 (위험 · 경고 · 주의만)
Color? riskBg(Risk r, HvColors c) => switch (r) {
      Risk.danger => c.dangerSoft,
      Risk.warning => c.warnSoft,
      Risk.caution => c.cautionSoft,
      _ => null,
    };

Color? riskInk(Risk r, HvColors c) => switch (r) {
      Risk.danger => c.danger,
      Risk.warning => c.warn,
      Risk.caution => c.caution,
      _ => null,
    };

/// 집 평면도. 주방 | 침실 | 욕실 세 공간을 나란히 붙여 그린다.
/// 지금 있는 방에 파란 점(퍼지는 원)과 재실 신뢰도, 위험한 방은 상태색 바탕,
/// 조명은 평면도에서 바로 켜고 끈다 (켜진 방은 따뜻한 색).
class HomeMap extends StatelessWidget {
  const HomeMap({super.key});

  @override
  Widget build(BuildContext context) {
    final c = context.hv;
    final state = context.select<HomeStore, HomeState>((s) => s.state);
    final rooms = roomsOf(state);
    final latest = state.latestSensing;
    return NowBuilder(
      builder: (context, now) => Container(
        padding: const EdgeInsets.all(2),
        decoration: BoxDecoration(color: c.line, borderRadius: BorderRadius.circular(12)),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            for (var i = 0; i < rooms.length; i++) ...[
              if (i > 0) const SizedBox(width: 2),
              Expanded(flex: rooms[i].id == HouseRoom.bathroom ? 100 : 112, child: _Cell(room: rooms[i], latest: latest, now: now)),
            ],
          ],
        ),
      ),
    );
  }
}

class _Cell extends StatelessWidget {
  const _Cell({required this.room, required this.latest, required this.now});
  final RoomInfo room;
  final SensingSample? latest;
  final DateTime now;

  @override
  Widget build(BuildContext context) {
    final c = context.hv;
    final r = room;
    final lit = r.lights.any((l) => l.online && l.on);
    final p = roomPresence(latest, r.id, now);
    final live = p.freshness == Freshness.live;
    final status = latest == null
        ? (r.here ? '사람 있음' : '확인 중')
        : !live
            ? '확인 중'
            : p.present
                ? (p.activity ?? '사람 있음')
                : '비어 있음';
    final radius = switch (r.id) {
      HouseRoom.kitchen => const BorderRadius.horizontal(left: Radius.circular(10)),
      HouseRoom.bathroom => const BorderRadius.horizontal(right: Radius.circular(10)),
      HouseRoom.bedroom => BorderRadius.zero,
    };
    final bg = riskBg(r.risk, c) ?? (lit ? Color.alphaBlend(c.glyphLight.withValues(alpha: 0.15), c.surface) : c.surface);
    return LayoutBuilder(builder: (context, box) {
      final wide = box.maxWidth >= 224;
      return Container(
        decoration: BoxDecoration(color: bg, borderRadius: radius),
        constraints: const BoxConstraints(minHeight: 80),
        child: Stack(
          children: [
            Positioned(
              left: 10,
              top: 10,
              right: 10,
              child: Text(houseRoomLabel[r.id]!,
                  style: ts(13, weight: w600, color: riskInk(r.risk, c) ?? (r.here ? c.brandInk : c.ink2))),
            ),
            if (r.here)
              Center(
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    LocateDot(size: wide ? 16 : 14, color: c.brand, ringColor: c.surface),
                    if (live && p.percent != null)
                      Padding(
                        padding: const EdgeInsets.only(top: 6),
                        child: Text('${p.percent}%', style: ts(wide ? 15 : 12, weight: w600, color: c.brandInk, tabular: true)),
                      ),
                  ],
                ),
              ),
            Positioned(
              left: 10,
              right: 10,
              bottom: 10,
              child: Text(status,
                  style: ts(12, weight: p.present && live ? w500 : w400, color: p.present && live ? c.ink : c.ink3),
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis),
            ),
            if (r.lights.isNotEmpty)
              Positioned(
                top: 2,
                right: 2,
                child: Row(
                  mainAxisSize: MainAxisSize.min,
                  children: [for (final l in r.lights) _LightButton(light: l, showLevel: box.maxWidth >= 136)],
                ),
              ),
          ],
        ),
      );
    });
  }
}

/// 평면도 칸 안 전구 버튼: 누르면 켜기/끄기. 켜져 있으면 밝기를 작게 함께 보여준다
class _LightButton extends StatelessWidget {
  const _LightButton({required this.light, required this.showLevel});
  final LightDevice light;
  final bool showLevel;

  @override
  Widget build(BuildContext context) {
    final c = context.hv;
    final l = light;
    final on = l.online && l.on;
    return Opacity(
      opacity: l.online ? 1 : 0.4,
      child: Pressable(
        onTap: l.online ? () => context.read<HomeStore>().controlDevice(l.id, DeviceControl(on: !l.on)) : null,
        semanticLabel: '${l.name} ${!l.online ? '응답 없음' : on ? '${brightnessLabel(l.brightness, savingLevel(l))} · 끄기' : '꺼짐 · 켜기'}',
        child: Container(
          constraints: const BoxConstraints(minWidth: 48, minHeight: 48),
          padding: const EdgeInsets.symmetric(horizontal: 8),
          child: Row(
            mainAxisSize: MainAxisSize.min,
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              if (on && showLevel)
                Padding(
                  padding: const EdgeInsets.only(right: 4),
                  child: Text(l.saving ? '절전' : '${l.brightness}%', style: ts(12, weight: w600, color: c.ink2, tabular: true)),
                ),
              SoftPulse(active: l.blinking, child: Icon(Ic.light, size: 24, color: on ? c.glyphLight : c.ink3)),
            ],
          ),
        ),
      ),
    );
  }
}
