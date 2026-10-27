"""
보드 마이크 음성 명령(버튼 방식)입니다. (v0.9, docs/VOICE.md 5장)

보드에는 브라우저 음성 인식이 없으므로 서버가 보드 마이크로 직접 녹음하고 음성 인식(STT)을 합니다.

흐름 (상태는 WebSocket voice.status로 알림):
1) POST /voice/listen -> start_listen(): listening. 이미 듣는 중이면 AlreadyListening(409)
2) 녹음 (pulseaudio parecord, 16kHz 모노)
   - 버튼 뒤 VOICE_LISTEN_START_SEC 안에 말소리가 없으면 failed(no_speech)
   - 말이 끝나고 VOICE_LISTEN_SILENCE_SEC 동안 조용하면, 또는 VOICE_LISTEN_MAX_SEC가 지나면 녹음 끝
   - 마이크를 열 수 없으면 failed(mic_unavailable)
3) recognizing -> OpenAI STT로 문장 + 신뢰도(confidence). 실패하면 failed(stt_error)
   인식된 문장을 담아 recognizing을 한 번 더 알립니다(대시보드가 "알아들은 문장"을 보여줌).
4) voice_service.submit_recognized(): 기존 흐름 (시작어 떼기 -> received -> thinking -> 판정 엔진 ...)
POST /voice/listen/cancel -> cancel_listen(): 녹음·인식 중이면 cancelled

한 번에 하나만 듣습니다. 녹음·인식은 별도 스레드에서 하므로 API는 바로 202를 돌려줍니다.
"""

import io
import logging
import math
import subprocess
import threading
import wave
from array import array
from collections import deque
from datetime import datetime, timedelta, timezone
from typing import Callable, Optional

import requests

from app import state_store, voice_service
from app.config import settings
from app.schemas import VoiceCommand

logger = logging.getLogger("induction.voice.listen")

SAMPLE_RATE = 16000
CHUNK_SEC = 0.1
CHUNK_BYTES = int(SAMPLE_RATE * CHUNK_SEC) * 2  # 16비트 모노 100ms
_PRE_ROLL_CHUNKS = 3  # 말소리 직전 0.3초도 같이 담아 첫 음절이 잘리지 않게
LISTENING = {"listening", "recognizing"}


class ListenDisabled(Exception):
    pass


class AlreadyListening(Exception):
    def __init__(self, voice_id: str):
        super().__init__(voice_id)
        self.voice_id = voice_id


class MicUnavailable(Exception):
    pass


class NoSpeech(Exception):
    pass


class SttError(Exception):
    pass


_lock = threading.Lock()
_active_id: Optional[str] = None
_cancel_events: dict[str, threading.Event] = {}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.isoformat(timespec="milliseconds")


def active_voice_id() -> Optional[str]:
    with _lock:
        return _active_id


def reset() -> None:
    """테스트용: 듣는 중 표시를 지웁니다."""
    global _active_id
    with _lock:
        _active_id = None
        _cancel_events.clear()


def _spawn(target: Callable, *args) -> None:
    threading.Thread(target=target, args=args, name="voice-listen", daemon=True).start()


# ---------------------------------------------------------------------------
# 1) 듣기 시작 / 취소
# ---------------------------------------------------------------------------

def start_listen(source: str = "button") -> VoiceCommand:
    global _active_id
    if not settings.VOICE_LISTEN_ENABLED:
        raise ListenDisabled()
    now = _now()
    # 녹음 + 인식에 걸릴 수 있는 최대 시간. 이 안에 판정 엔진에 넘기지 못하면 실패로 끝납니다.
    budget = settings.VOICE_LISTEN_START_SEC + settings.VOICE_LISTEN_MAX_SEC + settings.OPENAI_STT_TIMEOUT_SEC
    command = VoiceCommand(
        voiceId=voice_service.new_voice_id(),
        text="",
        source=source,
        receivedAt=_iso(now),
        status="listening",
        expiresAt=_iso(now + timedelta(seconds=budget)),
        updatedAt=_iso(now),
    )
    cancel = threading.Event()
    with _lock:
        if _active_id is not None:
            raise AlreadyListening(_active_id)
        _active_id = command.voiceId
        _cancel_events[command.voiceId] = cancel
    state_store.save_voice_command(command)
    voice_service.broadcast(command)
    logger.info("보드 마이크로 듣기 시작 (voiceId=%s, source=%s)", command.voiceId, source)
    _spawn(_run, command.voiceId, cancel)
    return command


def cancel_listen(voice_id: str) -> VoiceCommand:
    command = state_store.get_voice_command(voice_id)
    if command is None:
        raise voice_service.UnknownVoiceCommand(voice_id)
    with _lock:
        event = _cancel_events.get(voice_id)
    if event is not None:
        event.set()
    cancelled = state_store.transition_voice_command(voice_id, LISTENING, status="cancelled", updatedAt=_iso(_now()))
    if cancelled is None:
        raise voice_service.VoiceCommandError(409, f"듣는 중인 명령이 아닙니다 (현재 상태: {command.status}).")
    voice_service.broadcast(cancelled)
    logger.info("보드 마이크 듣기 취소 (voiceId=%s)", voice_id)
    return cancelled


def _run(voice_id: str, cancel: threading.Event) -> None:
    global _active_id
    try:
        try:
            pcm = record_utterance(cancel)
        except MicUnavailable as exc:
            logger.warning("마이크를 열 수 없습니다 (voiceId=%s): %s", voice_id, exc)
            voice_service.fail(voice_id, "mic_unavailable", LISTENING)
            return
        except NoSpeech:
            voice_service.fail(voice_id, "no_speech", LISTENING)
            return
        if cancel.is_set():
            return

        recognizing = state_store.transition_voice_command(
            voice_id, {"listening"}, status="recognizing", updatedAt=_iso(_now())
        )
        if recognizing is None:
            return
        voice_service.broadcast(recognizing)

        try:
            text, confidence = transcribe(to_wav(pcm))
        except SttError as exc:
            logger.warning("음성 인식 실패 (voiceId=%s): %s", voice_id, exc)
            voice_service.fail(voice_id, "stt_error", LISTENING)
            return
        if cancel.is_set():
            return
        text = " ".join(text.split())[:500]
        if not text:
            voice_service.fail(voice_id, "no_speech", LISTENING)
            return

        # 알아들은 문장을 먼저 보여주고(recognizing + text), 판정 엔진에 넘깁니다.
        shown = state_store.transition_voice_command(
            voice_id, {"recognizing"}, text=text, rawText=text, confidence=confidence, updatedAt=_iso(_now())
        )
        if shown is None:
            return
        voice_service.broadcast(shown)
        logger.info("보드 마이크 인식 (voiceId=%s, confidence=%s): %s", voice_id, confidence, text)
        voice_service.submit_recognized(voice_id, text, confidence)
    except Exception:
        logger.exception("보드 마이크 음성 명령 처리 중 오류 (voiceId=%s)", voice_id)
        voice_service.fail(voice_id, "stt_error", LISTENING)
    finally:
        with _lock:
            if _active_id == voice_id:
                _active_id = None
            _cancel_events.pop(voice_id, None)


# ---------------------------------------------------------------------------
# 2) 녹음 (말이 시작되면 담고, 끝나면 멈춤)
# ---------------------------------------------------------------------------

class _ParecordStream:
    """pulseaudio parecord로 16kHz 모노 16비트 원본 소리를 읽습니다."""

    def __init__(self) -> None:
        cmd = [settings.VOICE_RECORD_CMD, "--raw", "--format=s16le", f"--rate={SAMPLE_RATE}", "--channels=1"]
        if settings.VOICE_MIC_DEVICE:
            cmd.append(f"--device={settings.VOICE_MIC_DEVICE}")
        try:
            self._proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        except (FileNotFoundError, PermissionError) as exc:
            raise MicUnavailable(f"녹음 명령({settings.VOICE_RECORD_CMD})을 실행할 수 없습니다.") from exc

    def read(self, size: int) -> bytes:
        data = b""
        while len(data) < size:
            part = self._proc.stdout.read(size - len(data))
            if not part:
                break
            data += part
        return data

    def close(self) -> None:
        self._proc.terminate()
        try:
            self._proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            self._proc.kill()


def open_stream():
    return _ParecordStream()


def rms(chunk: bytes) -> float:
    samples = array("h")
    samples.frombytes(chunk[: len(chunk) - len(chunk) % 2])
    if not samples:
        return 0.0
    return math.sqrt(sum(s * s for s in samples) / len(samples))


def _chunks(seconds: float) -> int:
    return max(1, round(seconds / CHUNK_SEC))


def record_utterance(cancel: threading.Event) -> bytes:
    """말소리가 시작되면 녹음해 PCM(16kHz 모노 16비트)으로 돌려줍니다.
    마이크를 못 열면 MicUnavailable, 말소리가 없으면 NoSpeech. 취소되면 빈 값."""
    # 시간은 100ms 조각 수로 셉니다 (소수 덧셈 오차 없이)
    start_chunks = _chunks(settings.VOICE_LISTEN_START_SEC)
    silence_chunks = _chunks(settings.VOICE_LISTEN_SILENCE_SEC)
    max_chunks = _chunks(settings.VOICE_LISTEN_MAX_SEC)
    stream = open_stream()
    frames: list[bytes] = []
    pre_roll: deque = deque(maxlen=_PRE_ROLL_CHUNKS)
    started = False
    count = 0
    silence = 0
    try:
        while not cancel.is_set():
            chunk = stream.read(CHUNK_BYTES)
            if not chunk:
                if count == 0:
                    raise MicUnavailable("마이크에서 소리를 읽지 못했습니다.")
                break
            count += 1
            loud = rms(chunk) >= settings.VOICE_SPEECH_RMS
            if not started:
                pre_roll.append(chunk)
                if loud:
                    started = True
                    frames.extend(pre_roll)
                elif count >= start_chunks:
                    raise NoSpeech()
            else:
                frames.append(chunk)
                silence = 0 if loud else silence + 1
                if silence >= silence_chunks:
                    break
            if count >= max_chunks:
                break
    finally:
        stream.close()
    if cancel.is_set():
        return b""
    if not started:
        raise NoSpeech()
    return b"".join(frames)


def to_wav(pcm: bytes) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(SAMPLE_RATE)
        out.writeframes(pcm)
    return buffer.getvalue()


# ---------------------------------------------------------------------------
# 3) 음성 인식 (OpenAI)
# ---------------------------------------------------------------------------

def transcribe(wav: bytes) -> tuple[str, float]:
    """OpenAI STT로 (문장, 신뢰도 0~1)를 돌려줍니다. 응답 본문·키는 로그에 남기지 않습니다."""
    if not settings.OPENAI_API_KEY:
        raise SttError("OPENAI_API_KEY가 없습니다.")
    model = settings.OPENAI_STT_MODEL
    data = {"model": model, "language": "ko"}
    if model.startswith("whisper"):
        data["response_format"] = "verbose_json"
    else:
        data["response_format"] = "json"
        data["include[]"] = "logprobs"
    try:
        response = requests.post(
            f"{settings.OPENAI_BASE_URL.rstrip('/')}/audio/transcriptions",
            headers={"Authorization": f"Bearer {settings.OPENAI_API_KEY}"},
            files={"file": ("speech.wav", wav, "audio/wav")},
            data=data,
            timeout=settings.OPENAI_STT_TIMEOUT_SEC,
        )
    except requests.RequestException as exc:
        raise SttError(f"STT 요청 실패 ({type(exc).__name__})") from None
    if response.status_code != 200:
        raise SttError(f"STT 응답 HTTP {response.status_code}")
    try:
        body = response.json()
    except ValueError:
        raise SttError("STT 응답이 JSON이 아닙니다.") from None
    text = body.get("text") if isinstance(body, dict) else None
    if not isinstance(text, str):
        raise SttError("STT 응답에 text가 없습니다.")
    return text.strip(), confidence_from(body)


def confidence_from(body: dict) -> float:
    """인식 신뢰도 0~1.
    - logprobs(gpt-4o 계열): 토큰 로그확률 평균의 exp
    - segments(whisper verbose_json): 구간별 exp(avg_logprob) x (1 - no_speech_prob)의 평균
    - 둘 다 없으면 VOICE_STT_FALLBACK_CONFIDENCE"""
    values: list[float] = []
    logprobs = body.get("logprobs")
    if isinstance(logprobs, list):
        values = [p["logprob"] for p in logprobs if isinstance(p, dict) and isinstance(p.get("logprob"), (int, float))]
        if values:
            return _clamp(math.exp(sum(values) / len(values)))
    segments = body.get("segments")
    if isinstance(segments, list):
        scores = []
        for seg in segments:
            if isinstance(seg, dict) and isinstance(seg.get("avg_logprob"), (int, float)):
                no_speech = seg.get("no_speech_prob") if isinstance(seg.get("no_speech_prob"), (int, float)) else 0.0
                scores.append(math.exp(seg["avg_logprob"]) * (1.0 - no_speech))
        if scores:
            return _clamp(sum(scores) / len(scores))
    return _clamp(settings.VOICE_STT_FALLBACK_CONFIDENCE)


def _clamp(value: float) -> float:
    return round(min(max(value, 0.0), 1.0), 3)
