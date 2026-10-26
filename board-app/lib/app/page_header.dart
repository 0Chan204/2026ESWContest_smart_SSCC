import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../features/alerts/status_banner.dart';
import '../features/weather/weather_icon.dart';
import '../features/weather/weather_sheet.dart';
import '../models/types.dart';
import '../store/home_store.dart';
import '../store/preferences.dart';
import '../theme/theme.dart';
import '../ui/icons.dart';
import '../ui/sheet.dart';
import '../ui/widgets.dart';
import '../util/format.dart';
import 'canvas.dart';

/// 화면 상단: 큰 제목(iOS Large Title) + 월패드 시계 + 날씨. 어르신 모드는 글자 크기 조절 추가. 아래에 상태 배너.
class PageHeader extends StatelessWidget {
  const PageHeader({super.key, required this.title});
  final String title;

  @override
  Widget build(BuildContext context) {
    final c = context.hv;
    final elderly = context.elderly;
    final short = MediaQuery.sizeOf(context).height <= 760;
    return Column(
      mainAxisSize: MainAxisSize.min,
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Padding(
          padding: EdgeInsets.fromLTRB(32, short ? 16 : 24, 32, 0),
          child: NowBuilder(
            interval: const Duration(seconds: 10),
            builder: (context, now) => Row(
              crossAxisAlignment: CrossAxisAlignment.end,
              children: [
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      Text(formatToday(now), style: ts(elderly ? 18 : 13, weight: w600, color: c.ink3)),
                      Text(title,
                          style: ts(elderly ? 40 : 34, weight: w700, color: c.ink, height: 1.25, tracking: -0.02),
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis),
                    ],
                  ),
                ),
                if (elderly) ...[const FontScaleControl(), const SizedBox(width: 24)],
                _WeatherNow(hour: now.hour),
                const SizedBox(width: 24),
                Text(formatClock(now),
                    style: ts(elderly ? 52 : 44, weight: w300, color: c.ink, height: 1, tracking: -0.03, tabular: true)),
              ],
            ),
          ),
        ),
        const StatusBanner(),
      ],
    );
  }
}

/// 시계 옆 날씨: 아이콘 · 기온 · 상태(최고/최저). 누르면 자세히. 받아 둔 날씨가 없으면 안 보인다
class _WeatherNow extends StatelessWidget {
  const _WeatherNow({required this.hour});
  final int hour;

  @override
  Widget build(BuildContext context) {
    final w = context.select<HomeStore, Weather?>((s) => s.weather);
    if (w == null) return const SizedBox.shrink();
    final c = context.hv;
    final elderly = context.elderly;
    final icon = weatherIcon(w.code, hour, c);
    final sub = StringBuffer(w.condition);
    if (!elderly && w.max != null && w.min != null) sub.write(' · ${w.max!.round()}° / ${w.min!.round()}°');
    if (w.stale) sub.write(' · 지난 정보');
    return Pressable(
      onTap: () => showSheet(context, (_) => const WeatherSheet()),
      semanticLabel: '날씨 ${w.location} ${w.condition} ${w.temperature.round()}도 · 자세히 보기',
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(icon.icon, size: elderly ? 40 : 32, color: icon.color),
            const SizedBox(width: 10),
            Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              mainAxisSize: MainAxisSize.min,
              children: [
                Text('${w.temperature.round()}°',
                    style: ts(elderly ? 32 : 28, weight: w300, color: c.ink, height: 1.1, tracking: -0.02, tabular: true)),
                Text(sub.toString(), style: ts(elderly ? 16 : 13, color: c.ink3), maxLines: 1),
              ],
            ),
          ],
        ),
      ),
    );
  }
}

/// 글자 크기 조절 (어르신 모드)
class FontScaleControl extends StatelessWidget {
  const FontScaleControl({super.key});

  @override
  Widget build(BuildContext context) {
    final c = context.hv;
    final prefs = context.watch<Preferences>();
    final scale = prefs.fontScale;
    Widget btn(IconData icon, String label, bool enabled, VoidCallback onTap) => Opacity(
          opacity: enabled ? 1 : 0.3,
          child: Pressable(
            onTap: enabled ? onTap : null,
            semanticLabel: label,
            child: SizedBox(width: 48, height: 48, child: Icon(icon, size: 16, color: c.ink)),
          ),
        );
    return Container(
      padding: const EdgeInsets.all(2),
      decoration: BoxDecoration(color: c.fill, borderRadius: BorderRadius.circular(999)),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          btn(Ic.minus, '글자 작게', scale > fontScaleMin, () => prefs.setFontScale(scale - fontScaleStep)),
          ConstrainedBox(
            constraints: const BoxConstraints(minWidth: 64),
            child: Text('가 $scale%',
                textAlign: TextAlign.center,
                // 조절 버튼 글자는 배율을 따르지 않는다 (누를 자리가 흔들리지 않게)
                textScaler: TextScaler.noScaling,
                style: ts(14, weight: w600, color: c.ink, tabular: true)),
          ),
          btn(Ic.plus, '글자 크게', scale < fontScaleMax, () => prefs.setFontScale(scale + fontScaleStep)),
        ],
      ),
    );
  }
}
