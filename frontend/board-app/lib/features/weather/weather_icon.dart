import 'package:flutter/widgets.dart';

import '../../theme/tokens.dart';
import '../../ui/icons.dart';

class WeatherGlyph {
  const WeatherGlyph(this.icon, this.color);
  final IconData icon;
  final Color color;
}

/// WMO 날씨 코드 → 아이콘 (Open-Meteo 코드 체계). 밤(19~6시)에는 해 대신 달
WeatherGlyph weatherIcon(int code, int hour, HvColors c) {
  final night = hour >= 19 || hour < 6;
  if (code == 0) return night ? WeatherGlyph(Ic.moon, c.ink2) : WeatherGlyph(Ic.sun, c.glyphLight);
  if (code == 1 || code == 2) return night ? WeatherGlyph(Ic.cloudMoon, c.ink2) : WeatherGlyph(Ic.cloudSun, c.glyphLight);
  if (code == 45 || code == 48) return WeatherGlyph(Ic.cloudFog, c.ink3);
  if (code >= 51 && code <= 57) return WeatherGlyph(Ic.cloudDrizzle, c.glyphWater);
  if ((code >= 61 && code <= 67) || (code >= 80 && code <= 82)) return WeatherGlyph(Ic.cloudRain, c.glyphWater);
  if ((code >= 71 && code <= 77) || code == 85 || code == 86) return WeatherGlyph(Ic.cloudSnow, c.ink3);
  if (code >= 95) return WeatherGlyph(Ic.cloudLightning, c.glyphLight);
  return WeatherGlyph(Ic.cloud, c.ink3);
}
