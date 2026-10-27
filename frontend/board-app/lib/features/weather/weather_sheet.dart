import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../../models/types.dart';
import '../../store/home_store.dart';
import '../../theme/theme.dart';
import '../../ui/sheet.dart';
import '../../ui/widgets.dart';
import '../../util/format.dart';
import 'weather_icon.dart';

/// 이 확률 이상이면 '비 소식'
const rainPct = 30;

/// 시간대별 예보로 만든 안내 한 줄: 언제부터 비가 오는지 (없으면 null)
String? rainLine(List<HourlyWeather>? hourly, [DateTime? now]) {
  if (hourly == null) return null;
  HourlyWeather? first;
  for (final h in hourly) {
    if ((h.rainChance ?? 0) >= rainPct) {
      first = h;
      break;
    }
  }
  if (first == null) return null;
  final soon = secondsUntil(first.time, now ?? DateTime.now()) < 3600;
  return soon ? '지금 비 소식이 있어요. 외출할 때 우산을 챙기세요.' : '${koreanHour(first.time)}부터 비 소식이 있어요. 외출할 때 우산을 챙기세요.';
}

/// 날씨 자세히 — 시계 옆 날씨를 누르면 열린다.
/// 지금 날씨 · 안내 한 줄 · 시간대별 예보 띠 · 체감/습도/강수. 어르신 모드는 띠 없이 큰 글씨 안내만.
class WeatherSheet extends StatelessWidget {
  const WeatherSheet({super.key});

  @override
  Widget build(BuildContext context) {
    final w = context.select<HomeStore, Weather?>((s) => s.weather);
    final elderly = context.elderly;
    void close() => Navigator.of(context).maybePop();
    if (w == null) return SheetFrame(onClose: close, title: '날씨', child: const SizedBox(height: 40));
    final c = context.hv;
    final now = DateTime.now();
    final icon = weatherIcon(w.code, now.hour, c);
    String deg(double? v) => v == null ? '–' : '${v.round()}°';
    final line = rainLine(w.hourly, now) ?? (w.text.isEmpty ? null : w.text);
    final hourly = w.hourly;

    return SheetFrame(
      onClose: close,
      width: elderly ? 600 : 520,
      title: '날씨',
      subtitle: w.location.isEmpty ? null : Text(w.location),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          HvCard(
            padding: const EdgeInsets.all(20),
            child: Row(
              children: [
                Icon(icon.icon, size: 64, color: icon.color),
                const SizedBox(width: 20),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text('${w.temperature.round()}°', style: ts(56, weight: w200, color: c.ink, height: 1, tracking: -0.04, tabular: true)),
                      const SizedBox(height: 4),
                      Text(
                        '${w.condition}${w.max != null && w.min != null ? ' · 최고 ${deg(w.max)} 최저 ${deg(w.min)}' : ''}',
                        style: ts(elderly ? 20 : 17, color: c.ink2),
                      ),
                    ],
                  ),
                ),
              ],
            ),
          ),
          if (line != null)
            Padding(
              padding: const EdgeInsets.fromLTRB(4, 16, 4, 0),
              child: Text(line, style: ts(elderly ? 24 : 16, weight: elderly ? w600 : w400, color: c.ink, height: 1.55)),
            ),
          if (!elderly && hourly != null && hourly.length > 1)
            Padding(
              padding: const EdgeInsets.only(top: 24),
              child: Container(
                decoration: BoxDecoration(color: c.surface, borderRadius: BorderRadius.circular(12)),
                padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 12),
                child: SingleChildScrollView(
                  scrollDirection: Axis.horizontal,
                  child: Row(
                    children: [
                      for (var i = 0; i < hourly.length; i++) _HourCell(h: hourly[i], first: i == 0),
                    ],
                  ),
                ),
              ),
            ),
          const SizedBox(height: 24),
          ListGroup(
            footer: w.stale ? '인터넷 연결이 끊겨 마지막으로 받은 날씨를 보여주고 있어요.' : null,
            children: [
              ListRow(big: elderly, title: '체감 온도', value: deg(w.feels)),
              ListRow(big: elderly, title: '습도', value: w.humidity == null ? '–' : '${w.humidity!.round()}%'),
              ListRow(big: elderly, title: '오늘 비 올 확률', value: w.rainChance == null ? '–' : '${w.rainChance!.round()}%'),
            ],
          ),
        ],
      ),
    );
  }
}

class _HourCell extends StatelessWidget {
  const _HourCell({required this.h, required this.first});
  final HourlyWeather h;
  final bool first;

  @override
  Widget build(BuildContext context) {
    final c = context.hv;
    final hour = DateTime.tryParse(h.time)?.toLocal().hour ?? 0;
    final icon = weatherIcon(h.code, hour, c);
    final rainy = (h.rainChance ?? 0) >= rainPct;
    return SizedBox(
      width: 52,
      child: Column(
        children: [
          Text(first ? '지금' : '$hour시', style: ts(13, weight: first ? w600 : w400, color: first ? c.ink : c.ink3)),
          const SizedBox(height: 6),
          Icon(icon.icon, size: 24, color: icon.color),
          const SizedBox(height: 6),
          Text('${h.temperature.round()}°', style: ts(16, color: c.ink, tabular: true)),
          const SizedBox(height: 4),
          Opacity(
            opacity: rainy ? 1 : 0,
            child: Text('${(h.rainChance ?? 0).round()}%', style: ts(12, weight: w500, color: c.brandInk, tabular: true)),
          ),
        ],
      ),
    );
  }
}
