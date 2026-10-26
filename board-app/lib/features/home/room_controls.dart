import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../../models/types.dart';
import '../../store/home_store.dart';
import '../../theme/theme.dart';
import '../../ui/brightness_slider.dart';
import '../../ui/icons.dart';
import '../../ui/widgets.dart';
import '../../util/device_text.dart';
import '../../util/labels.dart';

/// 한 공간의 조작 줄 (React RoomControls): 조명 밝기 슬라이더 · 환풍기(약/중/강 · 스위치) · 공기청정기(스위치).
/// 어르신 모드는 이름과 큰 스위치만 둔다.
class RoomControls extends StatelessWidget {
  const RoomControls({super.key, required this.lights, required this.fans, required this.airs});
  final List<LightDevice> lights;
  final List<FanDevice> fans;
  final List<AirPurifierDevice> airs;

  @override
  Widget build(BuildContext context) {
    final elderly = context.elderly;
    final c = context.hv;
    final store = context.read<HomeStore>();
    final rows = <Widget>[
      for (final l in lights)
        elderly
            ? _SwitchRow(icon: Ic.light, glyph: c.glyphLight, name: '조명', device: l)
            : BrightnessSlider(
                large: true,
                name: '조명',
                disabled: !l.online,
                value: lightLevel(l),
                steps: l.brightnessSteps,
                savingLevel: savingLevel(l),
                onToggle: () => store.controlDevice(l.id, DeviceControl(on: !l.on)),
                onCommit: (v) => store.controlDevice(l.id, v <= 0 ? const DeviceControl(on: false) : DeviceControl(brightness: v)),
              ),
      for (final f in fans) elderly ? _SwitchRow(icon: Ic.fan, glyph: c.glyphFan, name: '환풍기', device: f) : _FanRow(fan: f),
      for (final a in airs) elderly ? _SwitchRow(icon: Ic.air, glyph: c.glyphAir, name: '공기청정기', device: a) : _AirRow(air: a),
    ];
    if (rows.isEmpty) return const SizedBox.shrink();
    return Column(
      mainAxisSize: MainAxisSize.min,
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        for (var i = 0; i < rows.length; i++) ...[if (i > 0) const SizedBox(height: 8), rows[i]],
      ],
    );
  }
}

/// 환풍기 한 줄: 아이콘 · 이름 · 약/중/강 · 스위치 (슬라이더와 같은 알약 모양)
class _FanRow extends StatelessWidget {
  const _FanRow({required this.fan});
  final FanDevice fan;

  @override
  Widget build(BuildContext context) {
    final c = context.hv;
    final f = fan;
    final on = f.online && f.on;
    final store = context.read<HomeStore>();
    return Opacity(
      opacity: f.online ? 1 : 0.4,
      child: Container(
        height: 64,
        padding: const EdgeInsets.only(left: 16, right: 4),
        decoration: BoxDecoration(color: c.fill, borderRadius: BorderRadius.circular(18)),
        child: LayoutBuilder(builder: (context, box) {
          final showName = box.maxWidth >= 300;
          return Row(
            children: [
              Icon(Ic.fan, size: 24, color: on ? c.glyphFan : c.ink3),
              const SizedBox(width: 10),
              if (showName)
                Expanded(child: Text('환풍기', style: ts(16, weight: w600, color: c.ink), maxLines: 1, overflow: TextOverflow.ellipsis))
              else
                const Spacer(),
              // 꺼져 있어도 마지막 풍량을 보여준다. 풍량을 고르면 그 풍량으로 켜진다
              ConstrainedBox(
                constraints: const BoxConstraints(maxWidth: 160),
                child: SizedBox(
                  width: showName ? 160 : (box.maxWidth - 140).clamp(96.0, 160.0),
                  child: Segmented<int>(
                    size: SegSize.touch,
                    value: f.speed,
                    options: const [SegOption(1, '약'), SegOption(2, '중'), SegOption(3, '강')],
                    onChanged: (v) {
                      if (f.online) store.controlDevice(f.id, DeviceControl(speed: v));
                    },
                  ),
                ),
              ),
              HvToggle(
                checked: on,
                disabled: !f.online,
                label: '${f.name} ${on ? '끄기' : '켜기'}',
                onChanged: (next) => store.controlDevice(f.id, DeviceControl(on: next)),
              ),
            ],
          );
        }),
      ),
    );
  }
}

/// 공기청정기 한 줄: 아이콘 · 이름 · 공기질 · 스위치. 자동으로 켜졌으면 이유를 보여준다
class _AirRow extends StatelessWidget {
  const _AirRow({required this.air});
  final AirPurifierDevice air;

  @override
  Widget build(BuildContext context) {
    final c = context.hv;
    final a = air;
    final on = a.online && a.on;
    final level = a.airQuality?.level;
    final line = (on ? airAutoReason(a, short: true) : null) ?? '${level != null ? '공기 ${airLevelLabel[level]} · ' : ''}${pm25Text(a)}';
    return Opacity(
      opacity: a.online ? 1 : 0.4,
      child: Container(
        height: 64,
        padding: const EdgeInsets.only(left: 16, right: 4),
        decoration: BoxDecoration(color: c.fill, borderRadius: BorderRadius.circular(18)),
        child: Row(
          children: [
            Icon(Ic.air, size: 24, color: on ? c.glyphAir : c.ink3),
            const SizedBox(width: 10),
            Expanded(
              child: Column(
                mainAxisAlignment: MainAxisAlignment.center,
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text('공기청정기', style: ts(16, weight: w600, color: c.ink), maxLines: 1, overflow: TextOverflow.ellipsis),
                  Text(a.online ? line : '응답 없음', style: ts(13, color: c.ink2), maxLines: 1, overflow: TextOverflow.ellipsis),
                ],
              ),
            ),
            HvToggle(
              checked: on,
              disabled: !a.online,
              label: '${a.name} ${on ? '끄기' : '켜기'}',
              onChanged: (next) => context.read<HomeStore>().controlDevice(a.id, DeviceControl(on: next)),
            ),
          ],
        ),
      ),
    );
  }
}

/// 어르신 모드: 이름과 큰 스위치만
class _SwitchRow extends StatelessWidget {
  const _SwitchRow({required this.icon, required this.glyph, required this.name, required this.device});
  final IconData icon;
  final Color glyph;
  final String name;
  final Device device;

  @override
  Widget build(BuildContext context) {
    final c = context.hv;
    final d = device;
    final on = d.online && deviceOn(d);
    final s = summarize(d);
    final short = MediaQuery.sizeOf(context).height <= 760;
    return Opacity(
      opacity: d.online ? 1 : 0.4,
      child: Container(
        constraints: BoxConstraints(minHeight: short ? 56 : 64),
        padding: const EdgeInsets.only(left: 16, right: 4),
        decoration: BoxDecoration(color: c.fill, borderRadius: BorderRadius.circular(18)),
        child: Row(
          children: [
            Icon(icon, size: 28, color: on ? glyph : c.ink3),
            const SizedBox(width: 12),
            Expanded(
              child: Column(
                mainAxisSize: MainAxisSize.min,
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(name, style: ts(20, weight: w600, color: c.ink), maxLines: 1, overflow: TextOverflow.ellipsis),
                  Text(
                    d.online ? (on || d is AirPurifierDevice ? s.status : '꺼짐') : '응답 없음',
                    style: ts(16, color: c.ink2),
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                  ),
                ],
              ),
            ),
            HvToggle(
              large: true,
              checked: on,
              disabled: !d.online,
              label: '${d.name} ${on ? '끄기' : '켜기'}',
              onChanged: (next) => context.read<HomeStore>().controlDevice(d.id, DeviceControl(on: next)),
            ),
          ],
        ),
      ),
    );
  }
}
