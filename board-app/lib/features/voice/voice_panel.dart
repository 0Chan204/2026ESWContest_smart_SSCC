import 'dart:math' as math;

import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../../app/canvas.dart';
import '../../theme/theme.dart';
import '../../ui/icons.dart';
import '../../ui/widgets.dart';
import '../../util/format.dart';
import 'voice_controller.dart';

/// 듣는 중에 보여줄 예시 (React EXAMPLE_COMMANDS)
const voiceExamples = ['욕실 조명 켜줘', '환풍기 세게', '오늘 날씨 어때'];

/// 음성 명령 패널 (React VoicePanel 자리 — 레일의 마이크 버튼 옆 왼쪽 아래). 음성 상태가 오면 저절로 뜬다.
class VoicePanelLayer extends StatelessWidget {
  const VoicePanelLayer({super.key});

  @override
  Widget build(BuildContext context) {
    final v = context.watch<VoiceController>();
    if (!v.open) return const SizedBox.shrink();
    final elderly = context.elderly;
    return Positioned(
      left: elderly ? 128 : 104,
      bottom: 20,
      width: elderly ? 440 : 380,
      child: VoicePanel(voice: v),
    );
  }
}

class VoicePanel extends StatelessWidget {
  const VoicePanel({super.key, required this.voice});
  final VoiceController voice;

  @override
  Widget build(BuildContext context) {
    final c = context.hv;
    final big = context.elderly;
    final v = voice;
    final text = switch (v.phase) {
      VoicePhase.completed => v.reply,
      VoicePhase.error => v.errorText,
      VoicePhase.processing || VoicePhase.starting || VoicePhase.listening || VoicePhase.recognizing => v.progress,
      VoicePhase.confirm || VoicePhase.idle => '',
    };
    final listening = v.phase == VoicePhase.listening;
    final micColor = v.phase == VoicePhase.error
        ? c.danger
        : v.phase == VoicePhase.completed
            ? c.ok
            : v.phase == VoicePhase.recognizing || v.phase == VoicePhase.starting
                ? c.brandInk
                : c.ink3;
    return Semantics(
      label: '음성 명령',
      liveRegion: true,
      child: Container(
        clipBehavior: Clip.antiAlias,
        decoration: BoxDecoration(color: c.surface, borderRadius: BorderRadius.circular(22), boxShadow: c.shadowPop),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Padding(
              padding: const EdgeInsets.only(left: 20, right: 6, top: 6),
              child: Row(
                children: [
                  Expanded(
                    child: Text(v.source == 'wakeword' ? '음성 명령 · 호출어' : '음성 명령',
                        style: ts(13, weight: w600, color: c.ink3), maxLines: 1, overflow: TextOverflow.ellipsis),
                  ),
                  Pressable(
                    onTap: v.close,
                    semanticLabel: '닫기',
                    child: SizedBox(
                      width: 48,
                      height: 48,
                      child: Center(
                        child: Container(
                          width: 30,
                          height: 30,
                          decoration: BoxDecoration(color: c.fill, shape: BoxShape.circle),
                          child: Icon(Ic.x, size: 16, color: c.ink2),
                        ),
                      ),
                    ),
                  ),
                ],
              ),
            ),
            Padding(
              padding: const EdgeInsets.fromLTRB(20, 0, 20, 20),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                mainAxisSize: MainAxisSize.min,
                children: [
                  Row(
                    children: [
                      if (listening)
                        const LevelBars(size: 40)
                      else
                        SizedBox(width: 40, height: 40, child: Center(child: Icon(Ic.mic, size: 32, color: micColor))),
                      const SizedBox(width: 16),
                      Expanded(
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          mainAxisSize: MainAxisSize.min,
                          children: [
                            if (v.heard.isNotEmpty)
                              Text('“${v.heard}”', style: ts(big ? 20 : 17, weight: w600, color: c.ink, height: 1.35)),
                            if (text.isNotEmpty)
                              Text(text,
                                  style: listening && v.heard.isEmpty
                                      ? ts(big ? 22 : 19, weight: w600, color: c.ink, height: 1.35)
                                      : ts(big ? 18 : 15, color: v.phase == VoicePhase.completed ? c.ink : c.ink2, height: 1.45)),
                          ],
                        ),
                      ),
                    ],
                  ),
                  if (v.phase == VoicePhase.confirm && v.confirmText != null) _Confirm(voice: v, big: big),
                  if (listening)
                    Padding(
                      padding: const EdgeInsets.only(top: 14),
                      child: Wrap(
                        spacing: 6,
                        runSpacing: 6,
                        children: [
                          for (final e in voiceExamples)
                            Container(
                              padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
                              decoration: BoxDecoration(color: c.fill, borderRadius: BorderRadius.circular(999)),
                              child: Text(e, style: ts(big ? 15 : 13, color: c.ink2)),
                            ),
                        ],
                      ),
                    ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}

/// 확인 창: 서버가 만든 문장 그대로 + 남은 시간
class _Confirm extends StatelessWidget {
  const _Confirm({required this.voice, required this.big});
  final VoiceController voice;
  final bool big;

  @override
  Widget build(BuildContext context) {
    final c = context.hv;
    final deadline = voice.confirmDeadline;
    return Padding(
      padding: const EdgeInsets.only(top: 16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        mainAxisSize: MainAxisSize.min,
        children: [
          Text(voice.confirmText!, style: ts(big ? 20 : 16, weight: w600, color: c.ink, height: 1.4)),
          if (deadline != null && DateTime.tryParse(deadline) != null)
            NowBuilder(builder: (context, now) {
              final left = secondsUntil(deadline, now).ceil().clamp(0, 9999);
              return Padding(
                padding: const EdgeInsets.only(top: 2),
                child: Text('$left초 뒤 자동으로 취소돼요', style: ts(13, color: c.ink3, tabular: true)),
              );
            }),
          const SizedBox(height: 12),
          Row(
            children: [
              Expanded(
                child: HvButton(
                  label: '취소',
                  variant: BtnVariant.secondary,
                  size: big ? BtnSize.xl : BtnSize.md,
                  expand: true,
                  onPressed: voice.cancel,
                ),
              ),
              const SizedBox(width: 8),
              Expanded(
                child: HvButton(
                  label: '실행',
                  variant: BtnVariant.primary,
                  size: big ? BtnSize.xl : BtnSize.md,
                  expand: true,
                  onPressed: voice.approve,
                ),
              ),
            ],
          ),
        ],
      ),
    );
  }
}

/// 듣는 중 표시: 높이가 오르내리는 막대 네 개 (React .wave)
class LevelBars extends StatefulWidget {
  const LevelBars({super.key, required this.size});
  final double size;
  @override
  State<LevelBars> createState() => _LevelBarsState();
}

class _LevelBarsState extends State<LevelBars> with SingleTickerProviderStateMixin {
  late final AnimationController _a = AnimationController(vsync: this, duration: const Duration(milliseconds: 1100))..repeat();

  @override
  void dispose() {
    _a.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final c = context.hv;
    final s = widget.size;
    return Semantics(
      label: '듣는 중',
      child: SizedBox(
        width: s,
        height: s,
        child: AnimatedBuilder(
          animation: _a,
          builder: (context, _) => Row(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              for (var i = 0; i < 4; i++)
                Container(
                  width: 4,
                  margin: const EdgeInsets.symmetric(horizontal: 1.5),
                  // 막대마다 조금씩 늦게 (0.35 ~ 1.0 높이)
                  height: s * 0.7 * (0.35 + 0.65 * (0.5 + 0.5 * math.sin(2 * math.pi * (_a.value - i * 0.18)))),
                  decoration: BoxDecoration(color: c.brand, borderRadius: BorderRadius.circular(2)),
                ),
            ],
          ),
        ),
      ),
    );
  }
}
