import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../../app/canvas.dart';
import '../../models/types.dart';
import '../../store/home_state.dart';
import '../../store/home_store.dart';
import '../../store/speaker.dart';
import '../../theme/theme.dart';
import '../../ui/icons.dart';
import '../../ui/sheet.dart';
import '../../ui/widgets.dart';
import '../../util/device_text.dart';
import '../../util/format.dart';
import '../../util/labels.dart';

/// 문자 알림 줄 (서버가 실제로 한 일만 말한다)
class FallSmsLine {
  const FallSmsLine(this.kind, this.text, {this.countdownTo});

  /// ok = 보냄 · wait = 본인 응답 대기 · warn = 못 보냄
  final String kind;
  final String text;

  /// wait 일 때 남은 시간을 셀 시각 (guardianAlertAt)
  final String? countdownTo;
}

/// 보호자 문자 결과 문장 (React FallAlertSheet 를 실제 발송 결과 기준으로 바꾼 것)
///  - guardianNotified → 보냈어요
///  - 본인 응답 대기(stage=user, pending) → n 후 보호자에게 알려요
///  - 연락처 없음 → 연락처가 없어 못 보냈어요 / 그 밖 → 보내지 못했어요
FallSmsLine fallSmsLine(FallIncident fall, Contact? guardian) {
  if (fall.guardianNotified) {
    return FallSmsLine('ok', guardian != null ? '보호자 ${guardian.name}님(${maskPhone(guardian.phone)})께 문자를 보냈어요' : '보호자에게 문자를 보냈어요');
  }
  if (fall.status == FallStatus.pending && fall.stage == FallStage.user && fall.guardianAlertAt != null) {
    return FallSmsLine('wait', '본인이 응답하지 않으면 보호자에게 알려요', countdownTo: fall.guardianAlertAt);
  }
  if (guardian == null) return const FallSmsLine('warn', '보호자 연락처가 없어 문자를 못 보냈어요');
  return const FallSmsLine('warn', '보호자에게 문자를 보내지 못했어요');
}

/// 대시보드 낙상 경보 (WS fall.incident). 서버가 이미 한 일(인덕션 비상 차단 · 문자)과
/// 남은 일(보호자 알림 · 자동 신고까지 시간)을 한 화면에 보여준다. 바깥을 눌러도 닫히지 않는다.
class FallAlertLayer extends StatefulWidget {
  const FallAlertLayer({super.key});

  @override
  State<FallAlertLayer> createState() => _FallAlertLayerState();
}

class _FallAlertLayerState extends State<FallAlertLayer> {
  String? _spokenFor;

  @override
  Widget build(BuildContext context) {
    final state = context.select<HomeStore, HomeState>((s) => s.state);
    final fall = state.fall;
    if (fall == null || !state.fallAlertOpen) return const SizedBox.shrink();
    final pending = fall.status == FallStatus.pending;
    if (pending && _spokenFor != fall.incidentId) {
      _spokenFor = fall.incidentId;
      final speaker = context.read<Speaker>();
      final text = fall.guardianNotified ? '욕실에서 넘어지신 것 같아요. 보호자에게 문자를 보냈어요.' : '욕실에서 넘어지신 것 같아요. 괜찮으시면 화면을 눌러 주세요.';
      WidgetsBinding.instance.addPostFrameCallback((_) => speaker.speak(text));
    }
    final store = context.read<HomeStore>();
    final elderly = context.elderly;
    final c = context.hv;
    final sms = fallSmsLine(fall, state.contacts.guardian);
    void close() => store.setFallAlert(false);

    return ModalLayer(
      child: SheetFrame(
        onClose: close,
        hideClose: true,
        width: elderly ? 680 : 560,
        footer: HvButton(
          label: pending ? '확인했어요' : '닫기',
          variant: pending ? BtnVariant.danger : BtnVariant.primary,
          size: elderly ? BtnSize.xl : BtnSize.lg,
          expand: true,
          onPressed: close,
        ),
        child: NowBuilder(
          builder: (context, now) => Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              const SizedBox(height: 12),
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 20),
                decoration: BoxDecoration(color: pending ? c.dangerFill : c.surface, borderRadius: BorderRadius.circular(18)),
                child: Row(
                  children: [
                    SoftPulse(active: pending, child: Icon(Ic.alert, size: 36, color: pending ? Colors.white : c.ink)),
                    const SizedBox(width: 16),
                    Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text('욕실 낙상 감지', style: ts(elderly ? 30 : 24, weight: w700, color: pending ? Colors.white : c.ink)),
                          Text(
                            '${formatTime(fall.detectedAt)}${elderly ? '' : ' · 정확도 ${(fall.confidence * 100).round()}%'}',
                            style: ts(elderly ? 18 : 15, color: pending ? Colors.white.withValues(alpha: 0.85) : c.ink2, tabular: true),
                          ),
                        ],
                      ),
                    ),
                  ],
                ),
              ),
              const SizedBox(height: 24),
              Container(
                clipBehavior: Clip.antiAlias,
                decoration: BoxDecoration(color: c.surface, borderRadius: BorderRadius.circular(12)),
                child: Column(
                  children: [
                    if (fall.burnerShutOff) _Step(first: true, icon: Ic.power, tone: c.ok, text: '켜져 있던 인덕션 전원을 껐어요'),
                    _Step(
                      first: !fall.burnerShutOff,
                      icon: sms.kind == 'ok' ? Ic.check : sms.kind == 'wait' ? Ic.clock : Ic.message,
                      tone: sms.kind == 'ok' ? c.ok : sms.kind == 'wait' ? c.warn : c.warn,
                      text: sms.text,
                      countdown: sms.countdownTo != null ? formatCountdown(secondsUntil(sms.countdownTo!, now)) : null,
                      countdownBefore: '본인이 응답하지 않으면 ',
                      countdownAfter: ' 후 보호자에게 알려요',
                    ),
                    if (pending)
                      _Step(
                        icon: Ic.clock,
                        tone: c.danger,
                        text: '',
                        countdown: formatCountdown(secondsUntil(fall.autoReportAt, now)),
                        countdownBefore: '응답이 없으면 ',
                        countdownAfter: ' 후 자동 신고',
                      )
                    else
                      _Step(
                        icon: Ic.check,
                        tone: fall.status == FallStatus.resolved ? c.ok : c.danger,
                        text: fallStatusLabel[fall.status]!,
                      ),
                  ],
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _Step extends StatelessWidget {
  const _Step({
    required this.icon,
    required this.tone,
    required this.text,
    this.first = false,
    this.countdown,
    this.countdownBefore = '',
    this.countdownAfter = '',
  });
  final IconData icon;
  final Color tone;
  final String text;
  final bool first;
  final String? countdown;
  final String countdownBefore;
  final String countdownAfter;

  @override
  Widget build(BuildContext context) {
    final c = context.hv;
    final big = context.elderly;
    final style = ts(big ? 20 : 16, color: c.ink, height: 1.35);
    return Padding(
      padding: const EdgeInsets.only(left: 16),
      child: Row(
        children: [
          Icon(icon, size: 20, color: tone),
          const SizedBox(width: 12),
          Expanded(
            child: Container(
              decoration: BoxDecoration(border: first ? null : Border(top: BorderSide(color: c.line))),
              padding: const EdgeInsets.fromLTRB(0, 14, 16, 14),
              child: countdown != null
                  ? Text.rich(
                      TextSpan(children: [
                        TextSpan(text: countdownBefore),
                        TextSpan(text: countdown, style: ts(big ? 20 : 16, weight: w700, color: c.ink, tabular: true)),
                        TextSpan(text: countdownAfter),
                      ]),
                      style: style,
                    )
                  : Text(text, style: style),
            ),
          ),
        ],
      ),
    );
  }
}
