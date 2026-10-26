import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../../app/app.dart';
import '../../app/page_header.dart';
import '../../config.dart';
import '../../models/types.dart';
import '../../store/home_store.dart';
import '../../store/preferences.dart';
import '../../theme/theme.dart';
import '../../ui/icons.dart';
import '../../ui/widgets.dart';
import '../../util/device_text.dart';

class _Section {
  const _Section(this.id, this.label, this.icon, this.color);
  final String id;
  final String label;
  final IconData icon;
  final SymColor color;
}

/// 보드 설정은 메모리에만 둔다 (읽기 전용 파일 시스템). 연락처 · 안전 정책 입력은 웹 대시보드에서 한다 (보드는 키보드가 없다).
const _sections = [
  _Section('display', '화면', Ic.sunMoon, SymColor.blue),
  _Section('contacts', '비상 연락처', Ic.phone, SymColor.green),
  _Section('about', '정보', Ic.info, SymColor.gray),
];

/// 설정 — iPad 설정 앱처럼 왼쪽 목록 / 오른쪽 내용 (React SettingsPage)
class SettingsPage extends StatelessWidget {
  const SettingsPage({super.key});

  @override
  Widget build(BuildContext context) {
    final c = context.hv;
    final elderly = context.elderly;
    final short = MediaQuery.sizeOf(context).height <= 760;
    final raw = context.select<NavState, String>((n) => n.settingsSection);
    final section = _sections.any((s) => s.id == raw) ? raw : 'display';
    final hasGuardian = context.select<HomeStore, bool>((s) => s.state.contacts.guardian != null);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        const PageHeader(title: '설정'),
        Expanded(
          child: Padding(
            padding: EdgeInsets.fromLTRB(32, short ? 16 : 20, 32, short ? 20 : 28),
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Expanded(
                  flex: 4,
                  child: Container(
                    clipBehavior: Clip.antiAlias,
                    decoration: BoxDecoration(color: c.surface, borderRadius: BorderRadius.circular(12)),
                    child: Column(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        for (var i = 0; i < _sections.length; i++)
                          _NavItem(
                            section: _sections[i],
                            selected: section == _sections[i].id,
                            first: i == 0,
                            big: elderly,
                            dot: _sections[i].id == 'contacts' && !hasGuardian,
                          ),
                      ],
                    ),
                  ),
                ),
                const SizedBox(width: 24),
                Expanded(
                  flex: 8,
                  child: SingleChildScrollView(
                    physics: const ClampingScrollPhysics(),
                    child: switch (section) {
                      'contacts' => const _ContactsSection(),
                      'about' => const _AboutSection(),
                      _ => const _DisplaySection(),
                    },
                  ),
                ),
              ],
            ),
          ),
        ),
      ],
    );
  }
}

class _NavItem extends StatelessWidget {
  const _NavItem({required this.section, required this.selected, required this.first, required this.big, required this.dot});
  final _Section section;
  final bool selected;
  final bool first;
  final bool big;
  final bool dot;

  @override
  Widget build(BuildContext context) {
    final c = context.hv;
    final short = MediaQuery.sizeOf(context).height <= 760;
    final item = Container(
      color: selected ? c.brand : Colors.transparent,
      padding: const EdgeInsets.only(left: 12),
      child: Row(
        children: [
          SymbolIcon(icon: section.icon, color: section.color),
          const SizedBox(width: 12),
          Expanded(
            child: Container(
              constraints: BoxConstraints(minHeight: big ? (short ? 56 : 64) : 48),
              padding: const EdgeInsets.only(right: 12),
              decoration: BoxDecoration(border: first || selected ? null : Border(top: BorderSide(color: c.line))),
              child: Row(
                children: [
                  Expanded(child: Text(section.label, style: ts(big ? 20 : 16, color: selected ? Colors.white : c.ink))),
                  if (dot)
                    Semantics(
                      label: '등록 필요',
                      child: Container(
                        width: 10,
                        height: 10,
                        decoration: BoxDecoration(color: selected ? Colors.white : c.warn, shape: BoxShape.circle),
                      ),
                    ),
                ],
              ),
            ),
          ),
        ],
      ),
    );
    return selected ? item : Pressable(onTap: () => context.read<NavState>().setSection(section.id), child: item);
  }
}

/// iOS 의 하나만 고르는 목록 (선택된 줄에 파란 체크)
class _Choice<T> extends StatelessWidget {
  const _Choice({required this.title, required this.value, required this.options, required this.onChanged, this.footer});
  final String title;
  final String? footer;
  final T value;
  final List<(T, String)> options;
  final ValueChanged<T> onChanged;

  @override
  Widget build(BuildContext context) {
    final c = context.hv;
    final elderly = context.elderly;
    return ListGroup(
      title: title,
      footer: footer,
      children: [
        for (final (v, label) in options)
          ListRow(
            big: elderly,
            title: label,
            onTap: () => onChanged(v),
            trailing: Opacity(
              opacity: v == value ? 1 : 0,
              child: Semantics(label: v == value ? '선택됨' : null, child: Icon(Ic.check, size: 20, color: c.brandInk)),
            ),
          ),
      ],
    );
  }
}

class _DisplaySection extends StatelessWidget {
  const _DisplaySection();

  @override
  Widget build(BuildContext context) {
    final prefs = context.watch<Preferences>();
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        _Choice<ThemeChoice>(
          title: '테마',
          footer: '시스템은 기기 설정을 따라가요.',
          value: prefs.theme,
          onChanged: prefs.setTheme,
          options: const [(ThemeChoice.light, '라이트'), (ThemeChoice.dark, '다크'), (ThemeChoice.system, '시스템')],
        ),
        const SizedBox(height: 24),
        _Choice<AppMode>(
          title: '화면 모드',
          footer: '어르신 모드는 꼭 필요한 정보만 크게 보여줘요. 보드를 다시 켜면 처음 설정으로 돌아가요.',
          value: prefs.mode,
          onChanged: prefs.setMode,
          options: const [(AppMode.normal, '일반'), (AppMode.elderly, '어르신')],
        ),
        if (prefs.elderly) ...[
          const SizedBox(height: 24),
          const ListGroup(title: '글자 크기', children: [ListRow(big: true, title: '크기', trailing: FontScaleControl())]),
        ],
      ],
    );
  }
}

/// 비상 연락처 — 보기만 한다 (등록 · 수정은 웹 대시보드). 공용 화면이라 번호 가운데를 가린다.
class _ContactsSection extends StatelessWidget {
  const _ContactsSection();

  @override
  Widget build(BuildContext context) {
    final elderly = context.elderly;
    final contacts = context.select<HomeStore, Contacts>((s) => s.state.contacts);
    final g = contacts.guardian;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        ListGroup(
          title: '보호자',
          footer: '낙상이 감지되면 이 번호로 확인 링크가 담긴 문자를 보내요.',
          children: [ListRow(big: elderly, title: g?.name ?? '등록 안 됨', value: g != null ? maskPhone(g.phone) : null)],
        ),
        const SizedBox(height: 24),
        ListGroup(
          title: '본인',
          footer: '연락처 등록 · 수정은 휴대폰이나 PC 의 HomeVIS 웹 화면에서 할 수 있어요.',
          children: [
            ListRow(big: elderly, title: contacts.user?.name ?? '등록 안 됨', value: contacts.user != null ? maskPhone(contacts.user!.phone) : null),
          ],
        ),
      ],
    );
  }
}

class _AboutSection extends StatelessWidget {
  const _AboutSection();

  @override
  Widget build(BuildContext context) {
    final elderly = context.elderly;
    final connected = context.select<HomeStore, bool>((s) => s.streamConnected);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        ListGroup(
          title: '정보',
          children: [
            ListRow(big: elderly, title: '버전', value: appVersion),
            ListRow(big: elderly, title: '데이터', value: connected ? '백엔드 연결됨' : '실시간 연결 끊김 · 다시 연결 중'),
            ListRow(big: elderly, title: '서버', valueWidget: _Mono(apiOrigin())),
            ListRow(big: elderly, title: '인덕션 원격 제어', value: '제공 안 함'),
            ListRow(big: elderly, title: '음성 명령', value: '진행 상황 표시'),
            ListRow(big: elderly, title: '외부 요청', value: '없음'),
          ],
        ),
      ],
    );
  }
}

class _Mono extends StatelessWidget {
  const _Mono(this.text);
  final String text;
  @override
  Widget build(BuildContext context) {
    final c = context.hv;
    return ConstrainedBox(
      constraints: const BoxConstraints(maxWidth: 320),
      child: Text(text, style: ts(15, color: c.ink2, tabular: true), maxLines: 1, overflow: TextOverflow.ellipsis),
    );
  }
}
