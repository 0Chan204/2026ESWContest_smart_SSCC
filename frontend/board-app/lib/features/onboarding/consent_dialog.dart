import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../../store/preferences.dart';
import '../../store/toaster.dart';
import '../../theme/theme.dart';
import '../../ui/sheet.dart';
import '../../ui/widgets.dart';
import 'permissions.dart';

/// 첫 실행 권한 동의 창 (React ConsentDialog).
/// 답하기 전에는 닫히지 않는다(바깥을 눌러도 그대로). 허용하면 음성 명령 · 음성 안내가 켜지고(호출어는 꺼진 채),
/// 나중에 설정 > 앱 권한에서 하나씩 바꿀 수 있다. 답은 설정 파일에 저장된다.
class ConsentLayer extends StatelessWidget {
  const ConsentLayer({super.key});

  @override
  Widget build(BuildContext context) {
    final elderly = context.elderly;
    void answer(bool granted) {
      context.read<Preferences>().answerConsent(granted);
      context.read<Toaster>().show(granted ? '권한을 허용했어요.' : '설정 > 앱 권한에서 언제든 바꿀 수 있어요.');
    }

    return ModalLayer(
      child: SheetFrame(
        onClose: () {/* 답하기 전에는 닫지 않는다 */},
        hideClose: true,
        width: elderly ? 620 : 520,
        title: 'HomeVIS 권한',
        subtitle: const Text('집을 지키는 데 아래 기능을 써요.'),
        footer: Row(
          children: [
            Expanded(
              child: HvButton(
                label: '허용 안 함',
                size: elderly ? BtnSize.xl : BtnSize.lg,
                expand: true,
                onPressed: () => answer(false),
              ),
            ),
            const SizedBox(width: 8),
            Expanded(
              child: HvButton(
                label: '허용',
                variant: BtnVariant.primary,
                size: elderly ? BtnSize.xl : BtnSize.lg,
                expand: true,
                onPressed: () => answer(true),
              ),
            ),
          ],
        ),
        child: ListGroup(
          footer: '설정 > 앱 권한에서 하나씩 바꿀 수 있어요.',
          children: [for (final p in permissions) PermissionRow(info: p, big: elderly)],
        ),
      ),
    );
  }
}

/// 권한 한 줄: 색 아이콘 · 이름(필수) · 설명 · 오른쪽 조작
class PermissionRow extends StatelessWidget {
  const PermissionRow({super.key, required this.info, required this.big, this.trailing});
  final PermissionInfo info;
  final bool big;
  final Widget? trailing;

  @override
  Widget build(BuildContext context) {
    final c = context.hv;
    return Padding(
      padding: const EdgeInsets.only(left: 16),
      child: Row(
        children: [
          SymbolIcon(icon: info.icon, color: info.color),
          const SizedBox(width: 12),
          Expanded(
            child: RowSeparator(
              child: Padding(
                padding: EdgeInsets.fromLTRB(0, big ? 12 : 10, 16, big ? 12 : 10),
                child: Row(
                  children: [
                    Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        mainAxisSize: MainAxisSize.min,
                        children: [
                          Text.rich(
                            TextSpan(children: [
                              TextSpan(text: info.title),
                              if (info.required) TextSpan(text: '  필수', style: ts(13, color: c.ink3)),
                            ]),
                            style: ts(big ? 20 : 16, color: c.ink),
                          ),
                          const SizedBox(height: 2),
                          Text(info.desc, style: ts(big ? 16 : 13, color: c.ink2, height: 1.35)),
                        ],
                      ),
                    ),
                    if (trailing != null) ...[const SizedBox(width: 12), trailing!],
                  ],
                ),
              ),
            ),
          ),
        ],
      ),
    );
  }
}
