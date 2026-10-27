import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../../models/types.dart';
import '../../store/home_store.dart';
import '../../theme/theme.dart';
import '../../theme/tokens.dart';
import '../../ui/icons.dart';
import '../../ui/sheet.dart';
import '../../ui/tile.dart';
import '../../ui/widgets.dart';
import '../../util/device_text.dart';
import '../../util/labels.dart';
import 'device_sheet.dart';

/// 기기 종류별 아이콘과 켜졌을 때 색 (조명 노랑 · 환기 청록 · 물 파랑 · 화구 주황 · 공기 초록)
(IconData, Color) deviceGlyph(DeviceKind kind, HvColors c) => switch (kind) {
      DeviceKind.induction => (Ic.induction, c.glyphHeat),
      DeviceKind.purifier => (Ic.water, c.glyphWater),
      DeviceKind.fan => (Ic.fan, c.glyphFan),
      DeviceKind.light => (Ic.light, c.glyphLight),
      DeviceKind.air => (Ic.air, c.glyphAir),
    };

void openDeviceSheet(BuildContext context, String deviceId) =>
    showSheet(context, (_) => DeviceSheet(deviceId: deviceId), variant: SheetVariant.side);

/// 홈 화면 기기 카드: 아이콘 / 이름 · 공간 / 상태 / 설명, 켜고 끌 수 있는 기기만 오른쪽 위 스위치.
/// 동작 중 = 밝은 카드, 꺼짐 · 대기 · 끊김 = 어두운 카드 + 흐린 글자. 인덕션 · 정수기는 조회 전용.
class DeviceCard extends StatelessWidget {
  const DeviceCard({super.key, required this.device});
  final Device device;

  @override
  Widget build(BuildContext context) {
    final c = context.hv;
    final d = device;
    final s = summarize(d);
    final (icon, glyph) = deviceGlyph(d.kind, c);
    final switchable = d.online && isControllable(d);
    final on = deviceOn(d);
    final active = d.online && s.active;
    final danger = s.risk == Risk.danger;
    final bg = danger ? c.dangerSoft : (active ? c.cardOn : c.tileOff);

    return Stack(
      fit: StackFit.expand,
      children: [
        Pressable(
          onTap: () => openDeviceSheet(context, d.id),
          semanticLabel: '${d.name} 자세히',
          child: Container(
            padding: const EdgeInsets.fromLTRB(20, 16, 20, 16),
            decoration: BoxDecoration(
              color: bg,
              borderRadius: BorderRadius.circular(18),
              boxShadow: active && !danger ? c.shadowTile : null,
              border: !active && !danger ? Border.all(color: c.line.withValues(alpha: 0.7)) : null,
            ),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Icon(icon, size: 28, color: danger ? c.danger : (active ? glyph : c.ink3.withValues(alpha: 0.7))),
                const Spacer(),
                Text.rich(
                  TextSpan(children: [
                    TextSpan(text: d.name),
                    TextSpan(text: ' · ${roomLabel[d.room]}', style: ts(14, color: c.ink3)),
                  ]),
                  style: ts(14, weight: w500, color: active || danger ? c.ink2 : c.ink3),
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                ),
                const SizedBox(height: 2),
                Row(
                  children: [
                    if (!d.online) ...[Icon(Ic.wifiOff, size: 16, color: c.ink2), const SizedBox(width: 6)],
                    Expanded(
                      child: Text(d.online ? s.status : '응답 없음',
                          style: ts(20, weight: w700, color: danger ? c.danger : (active ? c.ink : c.ink2)),
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis),
                    ),
                  ],
                ),
                const SizedBox(height: 2),
                Text(s.detail, style: ts(13, color: active ? c.ink2 : c.ink3), maxLines: 1, overflow: TextOverflow.ellipsis),
              ],
            ),
          ),
        ),
        if (switchable)
          Positioned(
            top: 2,
            right: 6,
            child: HvToggle(
              checked: on,
              label: '${d.name} ${on ? '끄기' : '켜기'}',
              onChanged: (next) => context.read<HomeStore>().controlDevice(d.id, DeviceControl(on: next)),
            ),
          ),
      ],
    );
  }
}

/// 기기 타일 (홈 앱):
///  - 조명 · 환풍기 · 공기청정기: 타일을 누르면 켜고 끈다, 오른쪽 아래 … 로 상세
///  - 인덕션 · 정수기: 조회 전용 — 누르면 상세 / 연결 끊김: 누르면 상세(다시 연결)
class DeviceTile extends StatelessWidget {
  const DeviceTile({super.key, required this.device, this.big = false});
  final Device device;
  final bool big;

  @override
  Widget build(BuildContext context) {
    final c = context.hv;
    final d = device;
    final (icon, glyph) = deviceGlyph(d.kind, c);
    final s = summarize(d);
    void open() => openDeviceSheet(context, d.id);
    if (!d.online) return Tile(icon: icon, name: d.name, state: '응답 없음', tone: TileTone.muted, onPress: open, big: big);
    switch (d) {
      case FanDevice() || LightDevice() || AirPurifierDevice():
        final on = deviceOn(d);
        return Tile(
          icon: icon,
          glyph: glyph,
          name: d.name,
          state: on || d is AirPurifierDevice ? s.status : '꺼짐',
          on: on,
          big: big,
          onPress: () => context.read<HomeStore>().controlDevice(d.id, DeviceControl(on: !on)),
          onMore: open,
        );
      case InductionDevice(:final burner):
        return Tile(
          icon: icon,
          glyph: glyph,
          name: d.name,
          state: s.status,
          on: burner.deviceState == BurnerState.on,
          tone: burner.deviceState == BurnerState.overheated ? TileTone.danger : null,
          onPress: open,
          big: big,
        );
      case PurifierDevice(:final dispensing):
        return Tile(icon: icon, glyph: glyph, name: d.name, state: s.status, on: dispensing, onPress: open, big: big);
    }
  }
}
