import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../../models/types.dart';
import '../../store/home_store.dart';
import '../../theme/theme.dart';
import '../../ui/brightness_slider.dart';
import '../../ui/charts.dart';
import '../../ui/sheet.dart';
import '../../ui/widgets.dart';
import '../../util/device_text.dart';
import '../../util/format.dart';
import '../../util/labels.dart';
import 'device_widgets.dart';

/// 기기 상세 (오른쪽 패널). iOS 설정처럼 묶음 목록으로 보여준다 (React DeviceSheet).
class DeviceSheet extends StatelessWidget {
  const DeviceSheet({super.key, required this.deviceId});
  final String deviceId;

  @override
  Widget build(BuildContext context) {
    final store = context.watch<HomeStore>();
    final d = store.state.deviceById(deviceId);
    final elderly = context.elderly;
    void close() => Navigator.of(context).maybePop();
    if (d == null) return SheetFrame(onClose: close, variant: SheetVariant.side, child: const SizedBox.shrink());
    final c = context.hv;
    final s = summarize(d);
    final (icon, glyph) = deviceGlyph(d.kind, c);
    final active = d.online && s.active;
    final big = elderly;
    final policy = store.state.policy;
    void control(DeviceControl ctl) => store.controlDevice(d.id, ctl);
    const gap = SizedBox(height: 24);

    final sections = <Widget>[];
    switch (d) {
      case InductionDevice(:final burner):
        sections.addAll([
          gap,
          ListGroup(
            title: '최근 3분 온도',
            bodyPadding: const EdgeInsets.fromLTRB(16, 16, 16, 8),
            children: [
              SizedBox(
                height: 96,
                child: Sparkline(
                  values: d.tempHistory,
                  max: policy.overheatEnterC + 15 > 170 ? policy.overheatEnterC + 15 : 170,
                  threshold: policy.overheatEnterC,
                  thresholdColor: c.danger,
                  color: burner.deviceState == BurnerState.overheated ? c.danger : c.glyphHeat,
                ),
              ),
              Padding(
                padding: const EdgeInsets.only(top: 4),
                child: Text('과열 ${policy.overheatEnterC.round()}°', textAlign: TextAlign.right, style: ts(12, color: c.danger)),
              ),
            ],
          ),
          gap,
          ListGroup(
            footer: '안전을 위해 이 화면에서는 켜거나 끌 수 없어요. 위험하면 HomeVIS 가 화력을 낮추거나 전원을 꺼요.',
            children: [
              ListRow(big: big, title: '화구', value: burnerLabel[burner.deviceState]),
              ListRow(big: big, title: '화력', value: burner.level > 0 ? '${burner.level} / 9단' : '0단'),
              ListRow(big: big, title: '온도', value: '${burner.temperature.toStringAsFixed(1)}°C'),
              ListRow(big: big, title: '조리 시간', value: burner.activeSec > 0 ? formatDuration(burner.activeSec) : '–'),
              ListRow(big: big, title: '마지막 변경', value: publisherLabel[d.lastControl]),
              ListRow(big: big, title: '과열 잠금', value: '${policy.overheatEnterC.round()}° 잠금 · ${policy.overheatExitC.round()}° 해제'),
            ],
          ),
        ]);
      case PurifierDevice(:final lastDispense, :final autoDispensedToday):
        sections.addAll([
          gap,
          ListGroup(
            footer: '아침에 일어나 30분 안에 주방에 오시면 물 한 컵(250mL)을 준비해요. 하루 한 번만.',
            children: [
              ListRow(
                  big: big,
                  title: '마지막 출수',
                  value: lastDispense != null ? '${formatWhen(lastDispense.at)} · ${lastDispense.ml.round()}mL' : '없음'),
              ListRow(big: big, title: '방식', value: (lastDispense?.auto ?? false) ? '아침 자동' : '직접'),
              ListRow(big: big, title: '오늘 자동 출수', value: autoDispensedToday ? '완료' : '아직'),
            ],
          ),
        ]);
      case FanDevice():
        sections.addAll([
          gap,
          ListGroup(children: [
            ListRow(
              big: big,
              title: '전원',
              trailing: HvToggle(checked: d.on, disabled: !d.online, large: big, label: '환풍기 전원', onChanged: (v) => control(DeviceControl(on: v))),
            ),
          ]),
          gap,
          ListGroup(
            title: '풍량',
            bodyPadding: const EdgeInsets.all(8),
            footer: d.room == RoomId.kitchen ? '조리를 시작하면 자동으로 켜져요. 직접 바꾸면 자동 운전이 잠시 꺼져요.' : '풍량을 고르면 그 풍량으로 켜져요.',
            children: [
              Segmented<int>(
                size: big ? SegSize.lg : SegSize.touch,
                value: d.speed,
                options: const [SegOption(1, '약'), SegOption(2, '중'), SegOption(3, '강')],
                onChanged: (v) {
                  if (d.online) control(DeviceControl(speed: v));
                },
              ),
            ],
          ),
        ]);
      case AirPurifierDevice():
        final aq = d.airQuality;
        sections.addAll([
          gap,
          ListGroup(children: [
            ListRow(
              big: big,
              title: '전원',
              trailing:
                  HvToggle(checked: d.on, disabled: !d.online, large: big, label: '공기청정기 전원', onChanged: (v) => control(DeviceControl(on: v))),
            ),
          ]),
          gap,
          ListGroup(
            title: '운전 모드',
            bodyPadding: const EdgeInsets.all(8),
            footer: '자동이면 공기질이 나쁠 때 스스로 켜지고, 좋아지면 꺼져요.',
            children: [
              Segmented<AirMode>(
                size: big ? SegSize.lg : SegSize.touch,
                value: d.mode,
                options: const [SegOption(AirMode.auto, '자동'), SegOption(AirMode.manual, '수동')],
                onChanged: (v) {
                  if (d.online) control(DeviceControl(mode: v));
                },
              ),
            ],
          ),
          gap,
          ListGroup(title: '공기질', children: [
            ListRow(big: big, title: '등급', value: aq?.level != null ? airLevelLabel[aq!.level] : '–'),
            ListRow(big: big, title: '초미세먼지 (PM2.5)', value: aq?.pm25 != null ? '${aq!.pm25!.round()} ㎍/㎥' : '–'),
            ListRow(big: big, title: '미세먼지 (PM10)', value: aq?.pm10 != null ? '${aq!.pm10!.round()} ㎍/㎥' : '–'),
            ListRow(
                big: big,
                title: '마지막 변경',
                value: d.on ? (airAutoReason(d) != null ? '자동' : '직접 켬') : (d.auto ? '자동으로 꺼짐' : '직접')),
          ]),
        ]);
      case LightDevice():
        sections.addAll([
          gap,
          ListGroup(children: [
            ListRow(
              big: big,
              title: '전원',
              trailing: HvToggle(checked: d.on, disabled: !d.online, large: big, label: '조명 전원', onChanged: (v) => control(DeviceControl(on: v))),
            ),
          ]),
          gap,
          ListGroup(
            title: '밝기',
            bodyPadding: const EdgeInsets.all(8),
            footer: d.brightnessSteps != null ? '끔 · 절전 20% · 100% 중에서 골라요. 절전은 천천히 어두워져요.' : '사람이 들어오면 켜지고, 나가면 꺼져요.',
            children: [
              BrightnessSlider(
                large: big,
                name: null,
                disabled: !d.online,
                value: lightLevel(d),
                steps: d.brightnessSteps,
                savingLevel: savingLevel(d),
                onToggle: () => control(DeviceControl(on: !d.on)),
                onCommit: (v) => control(v <= 0 ? const DeviceControl(on: false) : DeviceControl(brightness: v)),
              ),
            ],
          ),
        ]);
    }

    return SheetFrame(
      onClose: close,
      variant: SheetVariant.side,
      width: elderly ? 560 : 460,
      title: d.name,
      subtitle: Text(roomLabel[d.room] ?? ''),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          HvCard(
            padding: const EdgeInsets.all(20),
            child: Row(
              children: [
                Icon(icon, size: 40, color: s.risk == Risk.danger ? c.danger : (active ? glyph : c.ink3)),
                const SizedBox(width: 16),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(s.status, style: ts(big ? 30 : 24, weight: w700, color: s.risk == Risk.danger ? c.danger : c.ink)),
                      Text(s.detail, style: ts(big ? 18 : 15, color: c.ink2)),
                    ],
                  ),
                ),
              ],
            ),
          ),
          if (!d.online) _Reconnect(deviceId: d.id, big: big),
          ...sections,
        ],
      ),
    );
  }
}

/// 연결이 끊긴 기기: 다시 연결 (누르면 "연결 중…", 실패하면 그 자리에서 알린다)
class _Reconnect extends StatefulWidget {
  const _Reconnect({required this.deviceId, required this.big});
  final String deviceId;
  final bool big;
  @override
  State<_Reconnect> createState() => _ReconnectState();
}

class _ReconnectState extends State<_Reconnect> {
  bool _busy = false;
  bool _failed = false;

  Future<void> _run() async {
    setState(() {
      _busy = true;
      _failed = false;
    });
    final ok = await context.read<HomeStore>().reconnect(widget.deviceId);
    if (!mounted) return;
    setState(() {
      _busy = false;
      _failed = !ok;
    });
  }

  @override
  Widget build(BuildContext context) {
    final c = context.hv;
    return Padding(
      padding: const EdgeInsets.only(top: 24),
      child: ListGroup(
        footer: _failed ? null : '마지막으로 받은 상태를 보여주고 있어요.',
        children: [
          Padding(
            padding: const EdgeInsets.all(16),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                HvButton(
                  label: _busy ? '연결 중…' : '다시 연결',
                  variant: BtnVariant.primary,
                  size: widget.big ? BtnSize.xl : BtnSize.lg,
                  busy: _busy,
                  expand: true,
                  onPressed: _busy ? null : _run,
                ),
                if (_failed)
                  Padding(
                    padding: const EdgeInsets.only(top: 12),
                    child: Text('연결하지 못했어요 · 전원을 확인해 주세요',
                        textAlign: TextAlign.center, style: ts(14, weight: w500, color: c.danger)),
                  ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}
