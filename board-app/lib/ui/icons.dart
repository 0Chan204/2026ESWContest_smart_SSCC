// 아이콘 한곳 모음. React 의 lucide 아이콘을 lucide_icons(폰트 방식, 0.257)로 옮겼다.
// 이 버전에 없는 이름은 가장 가까운 모양으로 바꿨다 (CookingPot → soup, TriangleAlert → alertTriangle).

import 'package:flutter/widgets.dart';
import 'package:lucide_icons/lucide_icons.dart';

abstract final class Ic {
  static const IconData house = LucideIcons.home;
  static const IconData kitchen = LucideIcons.utensilsCrossed;
  static const IconData bath = LucideIcons.bath;
  static const IconData records = LucideIcons.clipboardList;
  static const IconData settings = LucideIcons.settings;
  static const IconData mic = LucideIcons.mic;
  static const IconData shieldCheck = LucideIcons.shieldCheck;
  static const IconData shieldAlert = LucideIcons.shieldAlert;
  static const IconData mapPin = LucideIcons.mapPin;
  static const IconData phone = LucideIcons.phone;
  static const IconData maximize = LucideIcons.maximize2;
  static const IconData refresh = LucideIcons.refreshCw;
  static const IconData chevronRight = LucideIcons.chevronRight;
  static const IconData chevronLeft = LucideIcons.chevronLeft;
  static const IconData wifiOff = LucideIcons.wifiOff;
  static const IconData user = LucideIcons.user;
  static const IconData radar = LucideIcons.radar;
  static const IconData lock = LucideIcons.lock;
  static const IconData flame = LucideIcons.flame;
  static const IconData gauge = LucideIcons.gauge;
  static const IconData power = LucideIcons.power;
  static const IconData thumbsUp = LucideIcons.thumbsUp;
  static const IconData thumbsDown = LucideIcons.thumbsDown;
  static const IconData alert = LucideIcons.alertTriangle;
  static const IconData clock = LucideIcons.clock3;
  static const IconData message = LucideIcons.messageSquare;
  static const IconData check = LucideIcons.check;
  static const IconData x = LucideIcons.x;
  static const IconData minus = LucideIcons.minus;
  static const IconData plus = LucideIcons.plus;
  static const IconData personStanding = LucideIcons.personStanding;
  static const IconData userX = LucideIcons.userX;
  static const IconData sunMoon = LucideIcons.sunMoon;
  static const IconData info = LucideIcons.info;
  static const IconData more = LucideIcons.moreHorizontal;
  static const IconData calendar = LucideIcons.calendar;
  static const IconData layout = LucideIcons.layoutGrid;

  // 기기
  static const IconData induction = LucideIcons.soup;
  static const IconData water = LucideIcons.droplet;
  static const IconData fan = LucideIcons.fan;
  static const IconData light = LucideIcons.lightbulb;
  static const IconData air = LucideIcons.airVent;

  // 날씨
  static const IconData sun = LucideIcons.sun;
  static const IconData moon = LucideIcons.moon;
  static const IconData cloud = LucideIcons.cloud;
  static const IconData cloudSun = LucideIcons.cloudSun;
  static const IconData cloudMoon = LucideIcons.cloudMoon;
  static const IconData cloudFog = LucideIcons.cloudFog;
  static const IconData cloudDrizzle = LucideIcons.cloudDrizzle;
  static const IconData cloudRain = LucideIcons.cloudRain;
  static const IconData cloudSnow = LucideIcons.cloudSnow;
  static const IconData cloudLightning = LucideIcons.cloudLightning;
}
