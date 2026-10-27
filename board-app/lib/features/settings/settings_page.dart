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
import '../../store/toaster.dart';
import '../../util/device_text.dart';
import '../onboarding/consent_dialog.dart';
import '../onboarding/permissions.dart';
import '../voice/voice_controller.dart';
import 'contact_sheet.dart';

class _Section {
  const _Section(this.id, this.label, this.icon, this.color);
  final String id;
  final String label;
  final IconData icon;
  final SymColor color;
}

/// 보드 설정은 $HOME/.config/homevis_gui/prefs.json 에 저장한다 (웹 빌드는 메모리).
/// 연락처는 키패드로 등록하고(서버 저장), 안전 정책 수정은 웹 대시보드에서 한다.
const _sections = [
  _Section('display', '화면', Ic.sunMoon, SymColor.blue),
  _Section('contacts', '비상 연락처', Ic.phone, SymColor.green),
  _Section('permissions', '앱 권한', Ic.shieldCheck, SymColor.indigo),
  _Section('voice', '음성', Ic.mic, SymColor.red),
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
                      'permissions' => const _PermissionsSection(),
                      'voice' => const _VoiceSection(),
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
          footer: '어르신 모드는 꼭 필요한 정보만 크게 보여줘요.',
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

/// 비상 연락처 — 보호자 · 본인. 등록 · 변경은 키패드 시트 (공용 화면이라 번호 가운데를 가린다)
class _ContactsSection extends StatelessWidget {
  const _ContactsSection();

  @override
  Widget build(BuildContext context) {
    final contacts = context.select<HomeStore, Contacts>((s) => s.state.contacts);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        _ContactGroup(
          kind: ContactKind.guardian,
          contact: contacts.guardian,
          title: '보호자',
          footer: '낙상이 감지되면 이 번호로 확인 링크가 담긴 문자를 보내요. 지금은 1명만 등록할 수 있어요.',
        ),
        const SizedBox(height: 24),
        _ContactGroup(
          kind: ContactKind.user,
          contact: contacts.user,
          title: '본인',
          footer: '문자에 누구 댁인지 표시하는 데 쓰여요. 저장하면 확인 문자가 갈 수 있어요. 번호는 서버에만 저장하고 화면에는 가운데를 가려서 보여 드려요.',
        ),
      ],
    );
  }
}

class _ContactGroup extends StatelessWidget {
  const _ContactGroup({required this.kind, required this.contact, required this.title, required this.footer});
  final ContactKind kind;
  final Contact? contact;
  final String title;
  final String footer;

  @override
  Widget build(BuildContext context) {
    final elderly = context.elderly;
    final c = contact;
    return ListGroup(
      title: title,
      footer: footer,
      children: [
        ListRow(
          big: elderly,
          title: c?.name ?? '등록 안 됨',
          value: c != null ? maskPhone(c.phone) : null,
          trailing: HvButton(
            label: c == null ? '등록' : '변경',
            variant: c == null ? BtnVariant.primary : BtnVariant.secondary,
            size: elderly ? BtnSize.lg : BtnSize.md,
            onPressed: () => openContactSheet(context, kind),
          ),
        ),
      ],
    );
  }
}

/// 음성 명령을 끄면 서버의 호출어 대기도 끈다 (마이크가 켜진 채 남지 않게)
void _setVoiceCommands(BuildContext context, bool on) {
  context.read<Preferences>().setVoiceCommands(on);
  final voice = context.read<VoiceController>();
  if (!on && voice.wakeWord) voice.setWakeWord(false);
  if (!on && voice.micActive) voice.close();
}

/// 앱 권한 — 첫 실행 동의 창에서 받은 권한을 하나씩 바꾼다 (React PermissionsSection)
class _PermissionsSection extends StatelessWidget {
  const _PermissionsSection();

  @override
  Widget build(BuildContext context) {
    final c = context.hv;
    final elderly = context.elderly;
    final prefs = context.watch<Preferences>();
    final hasGuardian = context.select<HomeStore, bool>((s) => s.state.contacts.guardian != null);
    Widget note(String t) => Text(t, style: ts(elderly ? 16 : 14, color: c.ink3));
    return ListGroup(
      title: '앱 권한',
      footer: '첫 실행 때 받은 동의를 여기서 바꿀 수 있어요.',
      children: [
        for (final p in permissions)
          PermissionRow(
            info: p,
            big: elderly,
            trailing: switch (p.key) {
              PermissionKey.presence => note('항상 사용'),
              PermissionKey.mic => HvToggle(
                  checked: prefs.voiceCommands,
                  large: elderly,
                  label: '마이크',
                  onChanged: (v) => _setVoiceCommands(context, v),
                ),
              PermissionKey.tts => HvToggle(checked: prefs.readAloud, large: elderly, label: '음성 안내', onChanged: prefs.setReadAloud),
              PermissionKey.contacts => hasGuardian
                  ? HvButton(
                      label: '등록됨',
                      variant: BtnVariant.quiet,
                      size: elderly ? BtnSize.lg : BtnSize.md,
                      onPressed: () => context.read<NavState>().setSection('contacts'),
                    )
                  : HvButton(
                      label: '등록',
                      variant: BtnVariant.ghost,
                      size: elderly ? BtnSize.lg : BtnSize.md,
                      onPressed: () => openContactSheet(context, ContactKind.guardian),
                    ),
            },
          ),
      ],
    );
  }
}

/// 음성 — 음성 명령(마이크 버튼) · 호출어(보드 음성 서비스 설정) · 위험 알림 음성 안내
class _VoiceSection extends StatefulWidget {
  const _VoiceSection();
  @override
  State<_VoiceSection> createState() => _VoiceSectionState();
}

class _VoiceSectionState extends State<_VoiceSection> {
  @override
  void initState() {
    super.initState();
    // 열 때마다 서버의 지금 값을 다시 읽는다 (없는 기능이면 조용히 '지원 안 함')
    context.read<VoiceController>().loadSettings();
  }

  @override
  Widget build(BuildContext context) {
    final elderly = context.elderly;
    final prefs = context.watch<Preferences>();
    final voice = context.watch<VoiceController>();
    final supported = voice.settingsSupported;
    final wakeEnabled = prefs.voiceCommands && supported == true && !voice.settingsBusy;
    String? wakeSub;
    if (supported == false) {
      wakeSub = '보드 음성 연결 후 사용할 수 있어요';
    } else if (!prefs.voiceCommands) {
      wakeSub = '음성 명령을 먼저 켜 주세요';
    } else if (voice.standby) {
      wakeSub = '지금 호출어를 기다리고 있어요';
    }
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        ListGroup(
          title: '음성 명령',
          footer: '왼쪽 아래 마이크 버튼으로 조명 · 환풍기 · 공기청정기를 말로 조작해요. 음성 인식 방식에 따라 음성이 외부 서버로 전송될 수 있어요.',
          children: [
            ListRow(
              big: elderly,
              title: '음성 명령 사용',
              trailing: HvToggle(
                checked: prefs.voiceCommands,
                large: elderly,
                label: '음성 명령 사용',
                onChanged: (v) => _setVoiceCommands(context, v),
              ),
            ),
          ],
        ),
        const SizedBox(height: 24),
        ListGroup(
          title: '호출어',
          footer: supported == false ? null : '켜 두면 “홈비스”라고 부를 때까지 보드 마이크가 계속 켜져 있어요. 처음에는 꺼져 있어요.',
          children: [
            ListRow(
              big: elderly,
              title: '호출어로 부르기 (홈비스)',
              subtitle: wakeSub,
              trailing: HvToggle(
                checked: voice.wakeWord && prefs.voiceCommands && supported == true,
                disabled: !wakeEnabled,
                large: elderly,
                label: '호출어로 부르기',
                onChanged: (v) async {
                  final toaster = context.read<Toaster>();
                  final ok = await voice.setWakeWord(v);
                  if (!ok) toaster.show('호출어 설정을 바꾸지 못했어요.', error: true);
                },
              ),
            ),
          ],
        ),
        const SizedBox(height: 24),
        ListGroup(
          title: '위험 알림',
          footer: '위험 알림이 뜨면 내용을 소리 내어 읽어 드려요.',
          children: [
            ListRow(
              big: elderly,
              title: '위험 알림 음성 안내',
              trailing: HvToggle(checked: prefs.readAloud, large: elderly, label: '위험 알림 음성 안내', onChanged: prefs.setReadAloud),
            ),
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
            ListRow(big: elderly, title: '음성 명령', value: '보드 마이크 · 진행 상황 표시'),
            if (context.read<Preferences>().storageLocation != null) ListRow(big: elderly, title: '설정 저장', value: '이 보드에 저장됨'),
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
