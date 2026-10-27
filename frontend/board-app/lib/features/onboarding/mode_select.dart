import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../../models/types.dart';
import '../../store/preferences.dart';
import '../../theme/theme.dart';
import '../../ui/icons.dart';
import '../../ui/widgets.dart';

/// 최초 1회 화면 모드 선택 (React ModeSelect). 고르면 저장되고, 이후에는 설정 > 화면 > 화면 모드에서만 바꾼다.
class ModeSelectScreen extends StatelessWidget {
  const ModeSelectScreen({super.key});

  @override
  Widget build(BuildContext context) {
    final c = context.hv;
    final short = MediaQuery.sizeOf(context).height <= 760;
    return Scaffold(
      backgroundColor: c.canvas,
      body: Center(
        child: SingleChildScrollView(
          physics: const ClampingScrollPhysics(),
          padding: EdgeInsets.symmetric(horizontal: 40, vertical: short ? 24 : 40),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Text('HomeVIS', style: ts(15, weight: w600, color: c.ink3)),
              const SizedBox(height: 4),
              Text('어떤 화면이 편하세요?',
                  textAlign: TextAlign.center, style: ts(40, weight: w700, color: c.ink, tracking: -0.02, height: 1.2)),
              const SizedBox(height: 8),
              Text('설정에서 언제든 바꿀 수 있어요.', textAlign: TextAlign.center, style: ts(17, color: c.ink2)),
              SizedBox(height: short ? 28 : 40),
              ConstrainedBox(
                constraints: const BoxConstraints(maxWidth: 760),
                child: const IntrinsicHeight(
                  child: Row(
                    crossAxisAlignment: CrossAxisAlignment.stretch,
                    children: [
                      Expanded(
                        child: _ModeCard(
                          mode: AppMode.elderly,
                          title: '크게 보기',
                          desc: '어르신께 추천',
                          sampleSize: 64,
                          points: ['글자와 버튼을 크게', '꼭 필요한 정보만', '쉬운 말로 안내'],
                        ),
                      ),
                      SizedBox(width: 16),
                      Expanded(
                        child: _ModeCard(
                          mode: AppMode.normal,
                          title: '기본 보기',
                          desc: '자세히 보고 싶을 때',
                          sampleSize: 40,
                          points: ['온도 · 기록까지 한눈에', '판단 근거와 정확도', '기기 세부 조절'],
                        ),
                      ),
                    ],
                  ),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _ModeCard extends StatelessWidget {
  const _ModeCard({required this.mode, required this.title, required this.desc, required this.sampleSize, required this.points});
  final AppMode mode;
  final String title;
  final String desc;
  final double sampleSize;
  final List<String> points;

  @override
  Widget build(BuildContext context) {
    final c = context.hv;
    final short = MediaQuery.sizeOf(context).height <= 760;
    return Pressable(
      onTap: () => context.read<Preferences>().setMode(mode),
      semanticLabel: '$title · $desc · 이 화면으로 시작',
      child: Container(
        padding: EdgeInsets.all(short ? 24 : 28),
        decoration: BoxDecoration(color: c.surface, borderRadius: BorderRadius.circular(22)),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            SizedBox(
              height: 64,
              child: Align(
                alignment: Alignment.bottomLeft,
                child: Text('가', style: ts(sampleSize, weight: w700, color: c.ink, height: 1)),
              ),
            ),
            SizedBox(height: short ? 18 : 24),
            Text(title, style: ts(24, weight: w700, color: c.ink)),
            Text(desc, style: ts(16, color: c.ink3)),
            SizedBox(height: short ? 14 : 20),
            for (final p in points)
              Padding(
                padding: const EdgeInsets.only(bottom: 8),
                child: Row(
                  children: [
                    Icon(Ic.check, size: 16, color: c.brandInk),
                    const SizedBox(width: 8),
                    Expanded(child: Text(p, style: ts(16, color: c.ink2), maxLines: 1, overflow: TextOverflow.ellipsis)),
                  ],
                ),
              ),
            const Spacer(),
            SizedBox(height: short ? 16 : 24),
            Container(
              constraints: const BoxConstraints(minHeight: 52),
              alignment: Alignment.center,
              decoration: BoxDecoration(color: c.brand, borderRadius: BorderRadius.circular(14)),
              child: Text('이 화면으로 시작', style: ts(17, weight: w600, color: Colors.white)),
            ),
          ],
        ),
      ),
    );
  }
}
