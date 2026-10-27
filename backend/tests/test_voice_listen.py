"""
v0.9: 보드 마이크 음성 명령(버튼 방식) · 음성 설정 · 보드 스피커 안내 테스트입니다.

실제 마이크·OpenAI·스피커 대신 가짜를 끼워
"버튼 -> 녹음 -> 인식 -> 판정 엔진 전달 -> 확인 창 -> 실행" 흐름과 실패 이유를 확인합니다.
"""

import threading
from array import array

import pytest
from fastapi.testclient import TestClient

from app import db, state_store, voice_listen_service, voice_service, voice_speaker
from app.config import settings
from app.schemas import VoiceCommand

PREFIX = settings.API_PREFIX
KITCHEN_LIGHT = "light-02"

LOUD = array("h", [3000, -3000] * 800).tobytes()   # 100ms, 말소리
QUIET = array("h", [0] * 1600).tobytes()           # 100ms, 조용함


@pytest.fixture()
def broadcasts(monkeypatch):
    from app import ws_hub

    sent: list[tuple[str, dict]] = []
    monkeypatch.setattr(ws_hub, "broadcast_threadsafe", lambda event, data: sent.append((event, data)))
    return sent


@pytest.fixture()
def inline(monkeypatch):
    """녹음·인식 스레드를 바로 실행해 API 응답 전에 끝나게 합니다."""
    monkeypatch.setattr(voice_listen_service, "_spawn", lambda target, *args: target(*args))


@pytest.fixture()
def spoken(monkeypatch):
    """보드 스피커로 읽으려던 문장을 모읍니다 (실제 TTS·재생 없음)."""
    texts: list[str] = []
    monkeypatch.setattr(settings, "VOICE_TTS_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "test-key", raising=False)
    monkeypatch.setattr(voice_speaker, "_submit", lambda text: texts.append(text) or True)
    voice_speaker._spoken_keys.clear()
    return texts


class FakeStream:
    def __init__(self, chunks):
        self.chunks = list(chunks)
        self.closed = False

    def read(self, size):
        return self.chunks.pop(0) if self.chunks else b""

    def close(self):
        self.closed = True


def _mic(monkeypatch, chunks):
    stream = FakeStream(chunks)
    monkeypatch.setattr(voice_listen_service, "open_stream", lambda: stream)
    return stream


def _stt(monkeypatch, text="홈비스 주방 불 켜줘", confidence=0.93):
    calls = []

    def fake(wav):
        calls.append(wav)
        return text, confidence

    monkeypatch.setattr(voice_listen_service, "transcribe", fake)
    return calls


def _statuses(broadcasts, voice_id):
    return [(d["status"], d.get("text"), d.get("reason")) for e, d in broadcasts if e == "voice.status" and d["voiceId"] == voice_id]


SPEECH = [QUIET] * 2 + [LOUD] * 5 + [QUIET] * 12


# ---------------------------------------------------------------------------
# 버튼 -> 녹음 -> 인식 -> 판정 엔진
# ---------------------------------------------------------------------------

def test_button_listen_to_engine_and_confirm(client, published, published_json, broadcasts, inline, monkeypatch):
    stream = _mic(monkeypatch, SPEECH)
    stt_calls = _stt(monkeypatch)

    res = client.post(f"{PREFIX}/voice/listen", json={})
    assert res.status_code == 202
    body = res.json()
    assert body["status"] == "listening"
    voice_id = body["voiceId"]

    assert _statuses(broadcasts, voice_id) == [
        ("listening", "", None),
        ("recognizing", "", None),
        ("recognizing", "홈비스 주방 불 켜줘", None),
        ("thinking", "주방 불 켜줘", None),
    ]
    assert stream.closed
    assert stt_calls[0][:4] == b"RIFF"  # WAV로 보냄

    topic, message = published_json[-1]
    assert topic == settings.VOICE_REQUEST_TOPIC
    assert (message["voiceId"], message["text"], message["rawText"]) == (voice_id, "주방 불 켜줘", "홈비스 주방 불 켜줘")
    assert (message["source"], message["wakeWord"], message["confidence"]) == ("button", True, 0.93)
    assert message["recognizedAt"] is not None

    # 이후는 기존 흐름 그대로: 확인 창 -> 실행
    client.post(
        f"{PREFIX}/ai/decisions",
        json={
            "decisionId": "dec-listen-1", "voiceId": voice_id, "scenario": "voice_command", "confidence": 0.9,
            "timestamp": "2026-10-27T21:00:00+09:00", "room": "kitchen", "announcement": "주방 조명을 켤게요.",
            "requiresConfirmation": True, "actions": [{"device": "light", "deviceId": KITCHEN_LIGHT, "action": "on"}],
        },
    )
    assert client.get(f"{PREFIX}/voice/commands/{voice_id}").json()["confirmText"] == "주방 조명을 켤까요?"
    done = client.post(f"{PREFIX}/voice/commands/{voice_id}/confirm", json={"approved": True}).json()
    assert done["status"] == "executed"
    assert (published[-1]["deviceId"], published[-1]["type"]) == (KITCHEN_LIGHT, "on")
    assert voice_listen_service.active_voice_id() is None


def test_no_speech(client, published_json, broadcasts, inline, monkeypatch):
    monkeypatch.setattr(settings, "VOICE_LISTEN_START_SEC", 0.5, raising=False)
    _mic(monkeypatch, [QUIET] * 10)
    stt_calls = _stt(monkeypatch)
    voice_id = client.post(f"{PREFIX}/voice/listen", json={}).json()["voiceId"]
    assert _statuses(broadcasts, voice_id)[-1] == ("failed", "", "no_speech")
    assert stt_calls == [] and published_json == []
    assert voice_listen_service.active_voice_id() is None


def test_wake_word_only_is_no_speech(client, published_json, broadcasts, inline, monkeypatch):
    _mic(monkeypatch, SPEECH)
    _stt(monkeypatch, text="홈비스")
    voice_id = client.post(f"{PREFIX}/voice/listen", json={}).json()["voiceId"]
    assert _statuses(broadcasts, voice_id)[-1][::2] == ("failed", "no_speech")
    assert published_json == []


def test_mic_unavailable(client, broadcasts, inline, monkeypatch):
    def broken():
        raise voice_listen_service.MicUnavailable("no device")

    monkeypatch.setattr(voice_listen_service, "open_stream", broken)
    voice_id = client.post(f"{PREFIX}/voice/listen", json={}).json()["voiceId"]
    assert _statuses(broadcasts, voice_id)[-1] == ("failed", "", "mic_unavailable")

    # 장치는 열렸지만 소리가 전혀 안 들어오는 경우도 같은 이유
    _mic(monkeypatch, [])
    voice_id = client.post(f"{PREFIX}/voice/listen", json={}).json()["voiceId"]
    assert _statuses(broadcasts, voice_id)[-1] == ("failed", "", "mic_unavailable")


def test_stt_error(client, published_json, broadcasts, inline, monkeypatch):
    _mic(monkeypatch, SPEECH)

    def fail(wav):
        raise voice_listen_service.SttError("HTTP 500")

    monkeypatch.setattr(voice_listen_service, "transcribe", fail)
    voice_id = client.post(f"{PREFIX}/voice/listen", json={}).json()["voiceId"]
    assert _statuses(broadcasts, voice_id)[-1] == ("failed", "", "stt_error")
    assert published_json == []
    assert client.get(f"{PREFIX}/voice/commands/{voice_id}").json()["reason"] == "stt_error"


def test_one_at_a_time_and_cancel(client, broadcasts, monkeypatch):
    monkeypatch.setattr(voice_listen_service, "_spawn", lambda target, *args: None)  # 듣는 중으로 남겨 둠
    first = client.post(f"{PREFIX}/voice/listen", json={}).json()["voiceId"]

    busy = client.post(f"{PREFIX}/voice/listen", json={})
    assert busy.status_code == 409
    assert busy.json()["detail"]["voiceId"] == first

    cancelled = client.post(f"{PREFIX}/voice/listen/cancel", json={"voiceId": first})
    assert cancelled.status_code == 200 and cancelled.json()["status"] == "cancelled"
    assert _statuses(broadcasts, first)[-1][0] == "cancelled"
    assert client.post(f"{PREFIX}/voice/listen/cancel", json={"voiceId": first}).status_code == 409
    assert client.post(f"{PREFIX}/voice/listen/cancel", json={"voiceId": "voice-x"}).status_code == 404


def test_cancel_during_recording_stops_flow(client, published_json, broadcasts, inline, monkeypatch):
    holder = {}

    class CancelStream(FakeStream):
        def read(self, size):
            if len(self.chunks) == 3:  # 말하는 도중 사용자가 패널을 닫음
                voice_listen_service.cancel_listen(holder["id"])
            return super().read(size)

    stream = CancelStream(SPEECH)
    monkeypatch.setattr(voice_listen_service, "open_stream", lambda: stream)
    stt_calls = _stt(monkeypatch)
    original = voice_listen_service._run

    def run(voice_id, cancel):
        holder["id"] = voice_id
        original(voice_id, cancel)

    monkeypatch.setattr(voice_listen_service, "_run", run)
    voice_id = client.post(f"{PREFIX}/voice/listen", json={}).json()["voiceId"]
    assert _statuses(broadcasts, voice_id)[-1][0] == "cancelled"
    assert stt_calls == [] and published_json == []
    assert voice_listen_service.active_voice_id() is None


def test_listen_disabled(client, monkeypatch):
    monkeypatch.setattr(settings, "VOICE_LISTEN_ENABLED", False, raising=False)
    res = client.post(f"{PREFIX}/voice/listen", json={})
    assert res.status_code == 503
    assert res.json()["detail"]["code"] == "LISTEN_DISABLED"


def test_listening_command_is_failed_after_restart(client, broadcasts):
    now = "2026-10-27T12:00:00.000+00:00"
    state_store.save_voice_command(VoiceCommand(
        voiceId="voice-old", text="", source="button", receivedAt=now, status="listening", expiresAt=now, updatedAt=now,
    ))
    voice_service.resume_pending()
    command = state_store.get_voice_command("voice-old")
    assert (command.status, command.reason) == ("failed", "interrupted")


# ---------------------------------------------------------------------------
# 녹음 끝 판정 · 인식 신뢰도 · OpenAI 요청 형식
# ---------------------------------------------------------------------------

def test_record_utterance_keeps_pre_roll_and_stops_on_silence(monkeypatch):
    monkeypatch.setattr(settings, "VOICE_LISTEN_SILENCE_SEC", 0.5, raising=False)
    stream = _mic(monkeypatch, [QUIET] * 4 + [LOUD] * 3 + [QUIET] * 10)
    pcm = voice_listen_service.record_utterance(threading.Event())
    # 말소리 시작 직전까지 0.3초(조용 2 + 첫 말소리 1) + 나머지 말소리 2 + 조용한 0.5초(5조각)에서 멈춤
    assert len(pcm) == voice_listen_service.CHUNK_BYTES * (3 + 2 + 5)
    assert len(stream.chunks) == 5 and stream.closed


def test_record_utterance_max_length(monkeypatch):
    monkeypatch.setattr(settings, "VOICE_LISTEN_MAX_SEC", 1.0, raising=False)
    _mic(monkeypatch, [LOUD] * 30)
    pcm = voice_listen_service.record_utterance(threading.Event())
    assert len(pcm) == voice_listen_service.CHUNK_BYTES * 10


def test_confidence_from_stt_response(monkeypatch):
    conf = voice_listen_service.confidence_from
    assert conf({"text": "불 켜줘", "logprobs": [{"token": "불", "logprob": -0.1}, {"token": "켜", "logprob": -0.3}]}) == 0.819
    assert conf({"text": "불 켜줘", "segments": [{"avg_logprob": -0.2, "no_speech_prob": 0.1}]}) == 0.737
    monkeypatch.setattr(settings, "VOICE_STT_FALLBACK_CONFIDENCE", 0.75, raising=False)
    assert conf({"text": "불 켜줘"}) == 0.75


class _Response:
    def __init__(self, status_code=200, body=None, content=b""):
        self.status_code = status_code
        self._body = body
        self.content = content

    def json(self):
        return self._body


def test_transcribe_request(monkeypatch):
    sent = {}

    def fake_post(url, **kwargs):
        sent.update(url=url, **kwargs)
        return _Response(body={"text": " 주방 불 켜줘 ", "logprobs": [{"logprob": 0.0}]})

    monkeypatch.setattr(voice_listen_service.requests, "post", fake_post)
    with pytest.raises(voice_listen_service.SttError):
        voice_listen_service.transcribe(b"RIFF")  # 키가 없으면 보내지 않음

    monkeypatch.setattr(settings, "OPENAI_API_KEY", "test-key", raising=False)
    assert voice_listen_service.transcribe(b"RIFF") == ("주방 불 켜줘", 1.0)
    assert sent["url"].endswith("/audio/transcriptions")
    assert sent["data"]["language"] == "ko" and sent["data"]["include[]"] == "logprobs"
    assert sent["files"]["file"][0] == "speech.wav"

    monkeypatch.setattr(settings, "OPENAI_STT_MODEL", "whisper-1", raising=False)
    voice_listen_service.transcribe(b"RIFF")
    assert sent["data"]["response_format"] == "verbose_json" and "include[]" not in sent["data"]

    monkeypatch.setattr(voice_listen_service.requests, "post", lambda url, **kw: _Response(status_code=429, body={}))
    with pytest.raises(voice_listen_service.SttError):
        voice_listen_service.transcribe(b"RIFF")


# ---------------------------------------------------------------------------
# 음성 설정 (GET/PUT /voice/settings, WebSocket voice.settings)
# ---------------------------------------------------------------------------

def test_voice_settings(client, broadcasts):
    assert client.get(f"{PREFIX}/voice/settings").json() == {"wakeWord": False, "standby": False, "speak": True}

    body = client.put(f"{PREFIX}/voice/settings", json={"wakeWord": True}).json()
    # 호출어 상시 듣기가 붙기 전까지 standby는 false
    assert body == {"wakeWord": True, "standby": False, "speak": True}
    assert ("voice.settings", body) in broadcasts

    body = client.put(f"{PREFIX}/voice/settings", json={"speak": False}).json()
    assert body == {"wakeWord": True, "standby": False, "speak": False}


def test_voice_settings_survive_restart(mongo, published):
    from app.main import app

    with TestClient(app) as client:
        client.put(f"{PREFIX}/voice/settings", json={"wakeWord": True, "speak": False})
    db.flush()
    state_store.reset_memory()
    with TestClient(app) as client:
        assert client.get(f"{PREFIX}/voice/settings").json() == {"wakeWord": True, "standby": False, "speak": False}


# ---------------------------------------------------------------------------
# 보드 스피커 안내
# ---------------------------------------------------------------------------

def _decide(client, voice_id, confirm, answer="주방 조명을 켤게요."):
    return client.post(
        f"{PREFIX}/ai/decisions",
        json={
            "decisionId": f"dec-{voice_id}", "voiceId": voice_id, "scenario": "voice_command", "confidence": 0.9,
            "timestamp": "2026-10-27T21:00:00+09:00", "room": "kitchen", "announcement": answer,
            "requiresConfirmation": bool(confirm),
            "actions": [{"device": "light", "deviceId": KITCHEN_LIGHT, "action": "on"}] if confirm is not None else [],
        },
    )


def _send(client, text="주방 불 켜줘"):
    return client.post(f"{PREFIX}/voice/commands", json={"text": text, "confidence": 0.9}).json()["voiceId"]


def test_speaker_reads_confirm_then_answer_once(client, published, spoken):
    voice_id = _send(client)
    _decide(client, voice_id, confirm=True)
    assert spoken == ["주방 조명을 켤까요?"]
    client.post(f"{PREFIX}/voice/commands/{voice_id}/confirm", json={"approved": True})
    assert spoken == ["주방 조명을 켤까요?", "주방 조명을 켤게요."]


def test_speaker_reads_answer_only_once(client, published, spoken):
    voice_id = _send(client, "지금 날씨 어때")
    _decide(client, voice_id, confirm=None, answer="지금은 맑아요.")
    assert spoken == ["지금은 맑아요."]


def test_speaker_reads_general_announcement(client, published, spoken):
    client.post(
        f"{PREFIX}/ai/decisions",
        json={"decisionId": "dec-ann", "scenario": "power_saving", "confidence": 0.9, "room": "room",
              "timestamp": "2026-10-27T21:00:00+09:00", "announcement": "아무도 없어 조명을 어둡게 할게요.", "actions": []},
    )
    assert spoken == ["아무도 없어 조명을 어둡게 할게요."]


def test_speaker_off_by_setting(client, published, spoken):
    client.put(f"{PREFIX}/voice/settings", json={"speak": False})
    voice_id = _send(client)
    _decide(client, voice_id, confirm=True)
    assert spoken == []


def test_synthesize_and_play(monkeypatch):
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "test-key", raising=False)
    sent = {}

    def fake_post(url, **kwargs):
        sent.update(url=url, **kwargs)
        return _Response(content=b"RIFFwav")

    monkeypatch.setattr(voice_speaker.requests, "post", fake_post)
    assert voice_speaker.synthesize("안녕하세요") == b"RIFFwav"
    assert sent["url"].endswith("/audio/speech")
    assert sent["json"]["input"] == "안녕하세요" and sent["json"]["response_format"] == "wav"

    played = {}
    real_run = voice_speaker.subprocess.run

    def fake_run(cmd, **kwargs):
        played["cmd"] = cmd
        return type("R", (), {"returncode": 0})()

    monkeypatch.setattr(voice_speaker.subprocess, "run", fake_run)
    monkeypatch.setattr(settings, "VOICE_SPEAKER_DEVICE", "hdmi", raising=False)
    voice_speaker.play(b"RIFFwav")
    assert played["cmd"][0] == settings.VOICE_PLAY_CMD and "--device=hdmi" in played["cmd"]

    monkeypatch.setattr(settings, "VOICE_PLAY_CMD", "no-such-player-cmd", raising=False)
    monkeypatch.setattr(voice_speaker.subprocess, "run", real_run)
    with pytest.raises(voice_speaker.TtsError):
        voice_speaker.play(b"RIFFwav")
