// 보드 연결 확인용 작은 앱: ${API_BASE}/health 를 불러 응답(JSON)이나 오류를 보여준다.
//
//   flutter-atlas build atlas --ipk --release -t lib/main_health.dart --dart-define=API_BASE=http://127.0.0.1:8000

import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:http/http.dart' as http;

import 'config.dart';
import 'theme/theme.dart';
import 'theme/tokens.dart';
import 'ui/widgets.dart';

void main() {
  WidgetsFlutterBinding.ensureInitialized();
  SystemChrome.setEnabledSystemUIMode(SystemUiMode.immersiveSticky);
  runApp(const HealthApp());
}

class HealthApp extends StatelessWidget {
  const HealthApp({super.key, this.client});
  final http.Client? client;

  @override
  Widget build(BuildContext context) => MaterialApp(
        title: 'HomeVIS health',
        debugShowCheckedModeBanner: false,
        theme: buildTheme(HvColors.light),
        home: HealthPage(client: client),
      );
}

class HealthPage extends StatefulWidget {
  const HealthPage({super.key, this.client});
  final http.Client? client;

  @override
  State<HealthPage> createState() => _HealthPageState();
}

class _HealthPageState extends State<HealthPage> {
  late final http.Client _client = widget.client ?? http.Client();
  bool _busy = false;
  int? _status;
  String? _body;
  String? _error;
  DateTime? _at;

  Uri get _url => Uri.parse('${apiOrigin()}/health');

  @override
  void initState() {
    super.initState();
    _check();
  }

  Future<void> _check() async {
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      final res = await _client.get(_url, headers: const {'Accept': 'application/json'}).timeout(const Duration(seconds: 8));
      var text = utf8.decode(res.bodyBytes);
      try {
        text = const JsonEncoder.withIndent('  ').convert(jsonDecode(text));
      } catch (_) {
        // JSON 이 아니면 그대로
      }
      if (!mounted) return;
      setState(() {
        _status = res.statusCode;
        _body = text.length > 4000 ? '${text.substring(0, 4000)}…' : text;
        _error = res.statusCode >= 200 && res.statusCode < 300 ? null : 'HTTP ${res.statusCode}';
      });
    } on TimeoutException {
      if (mounted) setState(() => _error = '응답이 없어요 (8초)');
    } catch (e) {
      if (mounted) setState(() => _error = '연결하지 못했어요');
    } finally {
      if (mounted) {
        setState(() {
          _busy = false;
          _at = DateTime.now();
        });
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final c = context.hv;
    final ok = _error == null && _status != null;
    String two(int n) => n.toString().padLeft(2, '0');
    return Scaffold(
      backgroundColor: c.canvas,
      body: SafeArea(
        child: Padding(
          padding: const EdgeInsets.all(32),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Row(
                children: [
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text('HomeVIS 연결 확인', style: ts(34, weight: w700, color: c.ink, tracking: -0.02)),
                        const SizedBox(height: 4),
                        Text('GET $_url', style: ts(15, color: c.ink2, tabular: true)),
                      ],
                    ),
                  ),
                  HvButton(label: _busy ? '확인 중…' : '다시 시도', variant: BtnVariant.primary, size: BtnSize.lg, busy: _busy, onPressed: _busy ? null : _check),
                ],
              ),
              const SizedBox(height: 24),
              Row(
                children: [
                  Container(width: 12, height: 12, decoration: BoxDecoration(color: _busy ? c.ink3 : (ok ? c.ok : c.danger), shape: BoxShape.circle)),
                  const SizedBox(width: 10),
                  Text(
                    _busy ? '확인 중' : (ok ? '정상 · HTTP $_status' : (_error ?? '')),
                    style: ts(20, weight: w600, color: _busy ? c.ink2 : (ok ? c.ok : c.danger)),
                  ),
                  const Spacer(),
                  if (_at != null) Text('${two(_at!.hour)}:${two(_at!.minute)}:${two(_at!.second)}', style: ts(15, color: c.ink3, tabular: true)),
                ],
              ),
              const SizedBox(height: 16),
              Expanded(
                child: Container(
                  width: double.infinity,
                  padding: const EdgeInsets.all(20),
                  decoration: BoxDecoration(color: c.surface, borderRadius: BorderRadius.circular(18)),
                  child: SingleChildScrollView(
                    child: Text(
                      _body ?? (_error != null ? '백엔드가 실행 중인지, API_BASE 가 맞는지 확인해 주세요.' : ''),
                      style: ts(16, color: c.ink, height: 1.5, tabular: true),
                    ),
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
