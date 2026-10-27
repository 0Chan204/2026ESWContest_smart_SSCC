"""
보드 스피커 음성 안내(TTS)입니다. (v0.9, docs/VOICE.md 5장)

보드에는 브라우저가 없어 대시보드가 소리를 낼 수 없으므로, 서버가 문장을 음성으로 바꿔(OpenAI TTS)
보드 스피커로 재생합니다(pulseaudio의 paplay).

- 읽는 것: 음성 명령의 확인 문구(confirm_required)와 답변(answered / executed),
           판정 엔진의 일반 안내(ai.announcement 중 음성 명령이 아닌 것)
- 끄고 켜기: GET/PUT /voice/settings 의 speak (기본 켜짐), .env VOICE_TTS_ENABLED, OPENAI_API_KEY가 없으면 읽지 않음
- 한 번에 하나씩 순서대로 읽고, 밀려 있는 문장이 많으면 새 문장은 버립니다(오래된 안내를 늦게 읽지 않도록).
- 읽는 중에는 is_speaking()이 true입니다. (다음 단계의 호출어 상시 듣기가 자기 소리를 듣지 않도록)
- 소리 장치나 인터넷이 없으면 로그만 남기고 넘어갑니다. 안내 실패가 제어·판단을 막지 않습니다.
"""

import logging
import os
import queue
import subprocess
import tempfile
import threading
from collections import deque
from typing import Optional

import requests

from app import state_store
from app.config import settings

logger = logging.getLogger("induction.voice.speaker")

_MAX_TEXT = 300
_QUEUE_SIZE = 3

_queue: "queue.Queue[str]" = queue.Queue(maxsize=_QUEUE_SIZE)
_worker: Optional[threading.Thread] = None
_worker_lock = threading.Lock()
_speaking = threading.Event()
_spoken_keys: deque = deque(maxlen=200)
_spoken_lock = threading.Lock()


class TtsError(Exception):
    pass


def enabled() -> bool:
    return bool(settings.VOICE_TTS_ENABLED and settings.OPENAI_API_KEY and state_store.get_voice_settings().speak)


def is_speaking() -> bool:
    return _speaking.is_set()


def speak(text: Optional[str]) -> bool:
    """문장을 읽기 대기열에 넣습니다. 읽지 않으면(꺼짐·빈 문장·대기열 가득) False"""
    text = (text or "").strip()
    if not text or not enabled():
        return False
    return _submit(text[:_MAX_TEXT])


def _once(key: tuple) -> bool:
    """같은 음성 명령의 같은 문장을 두 번 읽지 않도록 (voice.status는 같은 상태로 여러 번 올 수 있음)"""
    with _spoken_lock:
        if key in _spoken_keys:
            return False
        _spoken_keys.append(key)
        return True


def on_voice_status(command) -> None:
    """voice.status를 보낼 때마다 불립니다. 확인 문구와 답변을 한 번씩 읽습니다."""
    if not enabled():
        return
    if command.status == "confirm_required" and command.confirmText:
        if _once((command.voiceId, "confirm")):
            speak(command.confirmText)
    elif command.status in ("answered", "executed") and command.answer:
        if _once((command.voiceId, "answer")):
            speak(command.answer)


# ---------------------------------------------------------------------------
# 대기열과 재생 (테스트에서는 _submit을 바꿔 끼워 읽은 문장만 모읍니다)
# ---------------------------------------------------------------------------

def _enqueue(text: str) -> bool:
    _ensure_worker()
    try:
        _queue.put_nowait(text)
        return True
    except queue.Full:
        logger.warning("읽을 안내가 밀려 있어 새 안내를 건너뜁니다.")
        return False


_submit = _enqueue


def _ensure_worker() -> None:
    global _worker
    with _worker_lock:
        if _worker is None or not _worker.is_alive():
            _worker = threading.Thread(target=_run, name="voice-speaker", daemon=True)
            _worker.start()


def _run() -> None:
    while True:
        text = _queue.get()
        try:
            audio = synthesize(text)
            _speaking.set()
            play(audio)
        except TtsError as exc:
            logger.warning("음성 안내를 하지 못했습니다: %s", exc)
        except Exception:
            logger.exception("음성 안내 중 예상하지 못한 오류")
        finally:
            _speaking.clear()
            _queue.task_done()


def synthesize(text: str) -> bytes:
    """OpenAI TTS로 문장을 WAV로 바꿉니다. 응답 본문·키는 로그에 남기지 않습니다."""
    if not settings.OPENAI_API_KEY:
        raise TtsError("OPENAI_API_KEY가 없습니다.")
    try:
        response = requests.post(
            f"{settings.OPENAI_BASE_URL.rstrip('/')}/audio/speech",
            headers={"Authorization": f"Bearer {settings.OPENAI_API_KEY}"},
            json={
                "model": settings.OPENAI_TTS_MODEL,
                "voice": settings.OPENAI_TTS_VOICE,
                "input": text,
                "response_format": "wav",
            },
            timeout=settings.OPENAI_TTS_TIMEOUT_SEC,
        )
    except requests.RequestException as exc:
        raise TtsError(f"TTS 요청 실패 ({type(exc).__name__})") from None
    if response.status_code != 200 or not response.content:
        raise TtsError(f"TTS 응답 HTTP {response.status_code}")
    return response.content


def play(audio: bytes) -> None:
    """WAV를 보드 스피커로 재생합니다 (paplay). 끝날 때까지 기다립니다."""
    path = None
    try:
        with tempfile.NamedTemporaryFile(prefix="homevis-tts-", suffix=".wav", delete=False) as f:
            f.write(audio)
            path = f.name
        cmd = [settings.VOICE_PLAY_CMD]
        if settings.VOICE_SPEAKER_DEVICE:
            cmd.append(f"--device={settings.VOICE_SPEAKER_DEVICE}")
        cmd.append(path)
        result = subprocess.run(cmd, capture_output=True, timeout=60)
        if result.returncode != 0:
            raise TtsError(f"재생 실패 (exit {result.returncode})")
    except FileNotFoundError:
        raise TtsError(f"재생 명령({settings.VOICE_PLAY_CMD})이 없습니다.") from None
    except subprocess.TimeoutExpired:
        raise TtsError("재생 시간 초과") from None
    finally:
        if path:
            try:
                os.unlink(path)
            except OSError:
                pass
