import 'package:flutter/widgets.dart';
import 'package:provider/provider.dart';

import '../../store/home_state.dart';
import '../../store/home_store.dart';
import '../../store/speaker.dart';
import '../../store/toaster.dart';

/// AI 판정 엔진의 안내 문장(ai.announcement · weather.briefing)을 토스트로 띄우고 Speaker 로 넘긴다
/// (React AnnouncementSpeaker). 음성 명령 답변(voiceId 있음)은 translator 가 이미 걸러 음성 패널에만 보인다.
class AnnouncementWatcher extends StatefulWidget {
  const AnnouncementWatcher({super.key});

  @override
  State<AnnouncementWatcher> createState() => _AnnouncementWatcherState();
}

class _AnnouncementWatcherState extends State<AnnouncementWatcher> {
  String? _shown;

  @override
  Widget build(BuildContext context) {
    final a = context.select<HomeStore, Announcement?>((s) => s.state.announcement);
    if (a != null && a.id != _shown) {
      _shown = a.id;
      final toaster = context.read<Toaster>();
      final speaker = context.read<Speaker>();
      WidgetsBinding.instance.addPostFrameCallback((_) {
        toaster.show(a.text, duration: const Duration(seconds: 8));
        speaker.speak(a.text);
      });
    }
    return const SizedBox.shrink();
  }
}
