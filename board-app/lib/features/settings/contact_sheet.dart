import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../../data/home_source.dart';
import '../../models/types.dart';
import '../../store/home_store.dart';
import '../../store/toaster.dart';
import '../../theme/theme.dart';
import '../../ui/icons.dart';
import '../../ui/sheet.dart';
import '../../ui/widgets.dart';
import '../../util/phone.dart';

/// 보호자 관계 (고른 말이 그대로 이름(name)으로 저장된다)
const guardianRelations = ['보호자', '아들', '딸', '배우자', '손주', '이웃'];

/// 본인 연락처의 이름은 고정
const userContactName = '본인';

const _maxDigits = 11;

/// 연락처 등록 · 변경 시트를 연다 (설정 > 비상 연락처, 홈의 '보호자 · 등록 필요')
Future<void> openContactSheet(BuildContext context, ContactKind kind) => showSheet(context, (_) => ContactSheet(kind: kind));

/// 키보드 없는 연락처 입력 (보드는 터치만):
///  1) 보호자는 관계를 고른다 (보호자 · 아들 · 딸 · 배우자 · 손주 · 이웃) — 본인은 이름이 '본인'으로 고정
///  2) 큰 숫자 키패드로 번호를 누른다 ('010' 이 미리 들어 있음, 010-1234-5678 로 바로 묶어 보여준다)
///  저장 → PUT /guardian · /user { name, phone }. 서버에 SMS 키가 있으면 확인 문자가 간다.
class ContactSheet extends StatefulWidget {
  const ContactSheet({super.key, required this.kind});
  final ContactKind kind;

  @override
  State<ContactSheet> createState() => _ContactSheetState();
}

class _ContactSheetState extends State<ContactSheet> {
  late final bool _guardian = widget.kind == ContactKind.guardian;
  late final Contact? _existing = context.read<HomeStore>().state.contacts.of(widget.kind);
  late bool _pickRelation = _guardian;
  late String _name =
      !_guardian ? userContactName : (_existing?.name.trim().isNotEmpty == true ? _existing!.name.trim() : guardianRelations.first);

  // 번호는 공용 화면에 다시 보이지 않게 '010' 부터 새로 누른다
  String _digits = '010';
  String? _error;
  bool _busy = false;

  /// 웹에서 다른 이름으로 등록돼 있었다면 그 이름도 고를 수 있게 앞에 둔다
  List<String> get _relations {
    final e = _existing?.name.trim();
    return [if (_guardian && e != null && e.isNotEmpty && e.length <= 20 && !guardianRelations.contains(e)) e, ...guardianRelations];
  }

  void _press(String key) {
    if (_busy) return;
    setState(() {
      _error = null;
      if (key == 'del') {
        if (_digits.isNotEmpty) _digits = _digits.substring(0, _digits.length - 1);
      } else if (key == 'clear') {
        _digits = '';
      } else if (_digits.length < _maxDigits) {
        _digits += key;
      }
    });
  }

  String _errorText(Object e) {
    if (e is ApiError) {
      if (e.status == 422) return '번호 형식을 확인해 주세요.';
      if (e.status == 0) return '서버에 연결하지 못했어요. 잠시 후 다시 해 주세요.';
    }
    return '저장하지 못했어요. 잠시 후 다시 해 주세요.';
  }

  Future<void> _save() async {
    if (_busy) return;
    final digits = normalizePhone(_digits);
    if (digits == null) {
      setState(() => _error = _digits.length < 9 ? '번호를 끝까지 눌러 주세요.' : '번호 형식이 올바르지 않아요. 예: 010-1234-5678');
      return;
    }
    final store = context.read<HomeStore>();
    final toaster = context.read<Toaster>();
    final nav = Navigator.of(context);
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      final sent = await store.saveContact(widget.kind, Contact(name: _name, phone: digits));
      toaster.show(sent ? '저장했어요. 확인 문자를 보냈어요.' : '저장했어요. (확인 문자는 보내지 않았어요)');
      if (mounted) nav.pop();
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _busy = false;
        _error = _errorText(e);
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    final big = context.elderly;
    final close = Navigator.of(context).pop;
    final title = _guardian ? '보호자 연락처' : '본인 연락처';
    if (_pickRelation) {
      return SheetFrame(
        onClose: close,
        width: big ? 600 : 500,
        title: title,
        subtitle: Text('어떤 분인가요?', style: ts(big ? 18 : 15, color: context.hv.ink2)),
        footer: Row(
          children: [
            Expanded(
              child: HvButton(label: '취소', size: big ? BtnSize.xl : BtnSize.lg, expand: true, onPressed: close),
            ),
          ],
        ),
        child: Padding(
          padding: const EdgeInsets.only(top: 8),
          child: _RelationGrid(
            options: _relations,
            selected: _existing != null ? _name : null,
            big: big,
            onPick: (r) => setState(() {
              _name = r;
              _pickRelation = false;
            }),
          ),
        ),
      );
    }
    return SheetFrame(
      onClose: close,
      width: big ? 560 : 460,
      title: title,
      subtitle: Text('$_name${_guardian ? '님' : ''} 휴대폰 번호를 눌러 주세요', style: ts(big ? 18 : 15, color: context.hv.ink2)),
      footer: Row(
        children: [
          Expanded(
            child: HvButton(
              label: _guardian ? '이전' : '취소',
              size: big ? BtnSize.xl : BtnSize.lg,
              expand: true,
              onPressed: _busy ? null : () => _guardian ? setState(() => _pickRelation = true) : close(),
            ),
          ),
          const SizedBox(width: 8),
          Expanded(
            flex: 2,
            child: HvButton(
              label: _busy ? '저장 중…' : '저장',
              variant: BtnVariant.primary,
              size: big ? BtnSize.xl : BtnSize.lg,
              expand: true,
              busy: _busy,
              onPressed: _busy ? null : _save,
            ),
          ),
        ],
      ),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          const SizedBox(height: 8),
          _NumberDisplay(digits: _digits, big: big, error: _error != null),
          SizedBox(
            height: big ? 30 : 26,
            child: _error == null
                ? null
                : Padding(
                    padding: const EdgeInsets.only(top: 6, left: 4),
                    child: Semantics(
                      liveRegion: true,
                      child: Text(_error!,
                          style: ts(big ? 16 : 14, weight: w500, color: context.hv.danger), maxLines: 1, overflow: TextOverflow.ellipsis),
                    ),
                  ),
          ),
          NumberPad(onKey: _press, big: big),
        ],
      ),
    );
  }
}

/// 관계 고르기: 세 칸씩 큰 버튼
class _RelationGrid extends StatelessWidget {
  const _RelationGrid({required this.options, required this.selected, required this.big, required this.onPick});
  final List<String> options;
  final String? selected;
  final bool big;
  final ValueChanged<String> onPick;

  @override
  Widget build(BuildContext context) {
    final c = context.hv;
    final gap = big ? 12.0 : 10.0;
    final rows = <List<String>>[];
    for (var i = 0; i < options.length; i += 3) {
      rows.add(options.sublist(i, i + 3 > options.length ? options.length : i + 3));
    }
    return Column(
      mainAxisSize: MainAxisSize.min,
      children: [
        for (var r = 0; r < rows.length; r++) ...[
          if (r > 0) SizedBox(height: gap),
          Row(
            children: [
              for (var i = 0; i < 3; i++) ...[
                if (i > 0) SizedBox(width: gap),
                Expanded(
                  child: i >= rows[r].length
                      ? const SizedBox.shrink()
                      : Pressable(
                          onTap: () => onPick(rows[r][i]),
                          semanticLabel: rows[r][i],
                          child: Container(
                            height: big ? 76 : 64,
                            alignment: Alignment.center,
                            padding: const EdgeInsets.symmetric(horizontal: 8),
                            decoration: BoxDecoration(
                              color: rows[r][i] == selected ? c.brand : c.surface,
                              borderRadius: BorderRadius.circular(16),
                            ),
                            child: ExcludeSemantics(
                              child: Text(rows[r][i],
                                  style: ts(big ? 24 : 19, weight: w600, color: rows[r][i] == selected ? Colors.white : c.ink),
                                  maxLines: 1,
                                  overflow: TextOverflow.ellipsis),
                            ),
                          ),
                        ),
                ),
              ],
            ],
          ),
        ],
      ],
    );
  }
}

/// 누른 번호: 010-1234-5678 로 묶고, 남은 자리는 흐리게
class _NumberDisplay extends StatelessWidget {
  const _NumberDisplay({required this.digits, required this.big, required this.error});
  final String digits;
  final bool big;
  final bool error;

  @override
  Widget build(BuildContext context) {
    final c = context.hv;
    final shown = formatPhoneLive(digits);
    const template = '000-0000-0000';
    final rest = digits.startsWith('01') && digits.length < 11 && shown.length < template.length ? template.substring(shown.length) : '';
    final style = ts(big ? 40 : 34, weight: w600, color: c.ink, tabular: true, tracking: 0.02, height: 1.1);
    return Semantics(
      label: digits.isEmpty ? '번호 없음' : '입력한 번호 $shown',
      child: Container(
        height: big ? 76 : 66,
        padding: const EdgeInsets.symmetric(horizontal: 16),
        decoration: BoxDecoration(
          color: c.surface,
          borderRadius: BorderRadius.circular(16),
          border: Border.all(color: error ? c.danger : Colors.transparent, width: 1.5),
        ),
        alignment: Alignment.center,
        child: FittedBox(
          fit: BoxFit.scaleDown,
          child: ExcludeSemantics(
            child: Text.rich(
              TextSpan(children: [
                TextSpan(text: shown),
                if (rest.isNotEmpty) TextSpan(text: rest, style: style.copyWith(color: c.ink3.withValues(alpha: 0.45))),
              ]),
              style: style,
              maxLines: 1,
            ),
          ),
        ),
      ),
    );
  }
}

/// 큰 숫자 키패드 (전화 앱 배열). 키: '0'~'9', 'del'(지우기), 'clear'(전체 지우기)
class NumberPad extends StatelessWidget {
  const NumberPad({super.key, required this.onKey, this.big = false});
  final ValueChanged<String> onKey;
  final bool big;

  @override
  Widget build(BuildContext context) {
    final gap = big ? 10.0 : 8.0;
    const rows = [
      ['1', '2', '3'],
      ['4', '5', '6'],
      ['7', '8', '9'],
      ['clear', '0', 'del'],
    ];
    return Column(
      mainAxisSize: MainAxisSize.min,
      children: [
        for (var r = 0; r < rows.length; r++) ...[
          if (r > 0) SizedBox(height: gap),
          Row(
            children: [
              for (var i = 0; i < 3; i++) ...[
                if (i > 0) SizedBox(width: gap),
                Expanded(child: _Key(k: rows[r][i], big: big, onKey: onKey)),
              ],
            ],
          ),
        ],
      ],
    );
  }
}

class _Key extends StatelessWidget {
  const _Key({required this.k, required this.big, required this.onKey});
  final String k;
  final bool big;
  final ValueChanged<String> onKey;

  @override
  Widget build(BuildContext context) {
    final c = context.hv;
    final digit = k.length == 1;
    final label = switch (k) { 'del' => '지우기', 'clear' => '전체 지우기', _ => k };
    return Pressable(
      onTap: () => onKey(k),
      semanticLabel: label,
      child: Container(
        height: big ? 68 : 56,
        alignment: Alignment.center,
        decoration: BoxDecoration(color: digit ? c.surface : c.fill, borderRadius: BorderRadius.circular(14)),
        child: ExcludeSemantics(
            child: digit
                ? Text(k, style: ts(big ? 34 : 28, weight: w500, color: c.ink, tabular: true, height: 1))
                : k == 'del'
                    ? Icon(Ic.delete, size: big ? 30 : 26, color: c.ink2)
                    : Text('전체 지우기', style: ts(big ? 18 : 15, weight: w600, color: c.ink2), maxLines: 1)),
      ),
    );
  }
}
