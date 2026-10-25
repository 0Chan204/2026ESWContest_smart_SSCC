"""Offline voice contracts, safety, persistence and real legacy feedback integration."""
from copy import deepcopy
from dataclasses import replace
import json
from threading import Event
import time
from types import SimpleNamespace

import pytest

from examples.backend_integration_demo import FakeClock
from src.alert_service import AlertService
from src.integration.backend_client import BackendClient, BackendError, HTTPResult
from src.integration.backend_sensing import BackendSensingSource
from src.integration.mock_backend import sample_devices
from src.integration.mqtt_source import CombinedSource, Incoming, InputRouter, MQTTSource
from src.integration.runtime import IntegrationRuntime
from src.integration.schemas import ContractError, iso_time, measured_time
from src.integration.settings import load_settings
from src.interaction.config import VoiceConfig
from src.interaction.contracts import request_message, decision_payload, decision_response, action_payload, command_list
from src.interaction.control import propose_control
from src.interaction.explanation import ExplanationService, policy_snapshot
from src.interaction.intent import IntentClassifier, INTENTS
from src.interaction.response import FALLBACK
from src.llm.message_generator import LLMMessageGenerator
from src.llm.shared import SharedLLM
from src.voice.tts import DryRunTTS

BASE = measured_time("2026-10-24T12:00:00+00:00")


def message(text="욕실 전등 켜줘", key="voice-1", now=BASE, **extra):
    return {"voiceId": key, "text": text, "lang": "ko-KR", "confidence": .92, "source": "voice",
            "recognizedAt": iso_time(now), "receivedAt": iso_time(now), "expiresAt": iso_time(now + 10), **extra}


def intent(text, labels=("control_request",), **extra):
    return {"intents": list(labels), "confidence": .96, "device": "light", "room": "toilet", "action": "on",
            "query": None, "parameters": {}, "evidence": {i: text for i in labels}, **extra}


class FakeLLM:
    name = "mock"
    def __init__(self):
        self.responses, self.calls = [], []

    def generate(self, system_prompt, user_prompt):
        self.calls.append((system_prompt, user_prompt))
        value = self.responses.pop(0)
        if callable(value):
            value = value()
        if isinstance(value, Exception):
            raise value
        return json.dumps(value, ensure_ascii=False) if isinstance(value, dict) else value


class VoiceTransport:
    mock_only = True
    def __init__(self, clock):
        self.clock = clock
        self.calls, self.decisions, self.recover, self.old_commands = [], {}, [], []
        self.fail_post = None
        self.weather = {"available": True, "text": "서울은 맑습니다.", "stale": True, "basedOn": iso_time(BASE - 3600)}
        self.presence = {"resultId": "sensing-1", "observedAt": iso_time(BASE), "savedAt": iso_time(BASE),
                         "room": "kitchen", "present": True, "confidence": .9, "validSec": 20}
        self.sensing = []
        self.devices = sample_devices(BASE)["items"]
        self.devices.extend([
            {"device": "light", "deviceId": "light-00", "room": "toilet", "online": True, "is_on": False,
             "current_state": {"power": "off"}, "control_state": None, "updatedAt": iso_time(BASE)},
            {"device": "fan", "deviceId": "fan-01", "room": "kitchen", "online": True, "is_on": False,
             "current_state": {"power": "off", "speed": "low"}, "control_state": None, "updatedAt": iso_time(BASE)}])

    def request(self, method, url, headers, body, timeout):
        path = url.split("/api/v1", 1)[1]
        payload = None if body is None else json.loads(body)
        self.calls.append((method, path, deepcopy(payload), timeout))
        if method == "POST":
            if self.fail_post:
                error, self.fail_post = self.fail_post, None
                raise error
            key = payload["decisionId"]
            duplicate = key in self.decisions
            if not duplicate:
                pending = payload.get("requiresConfirmation", False)
                self.decisions[key] = {**deepcopy(payload), "receivedAt": iso_time(self.clock()),
                    "status": "awaiting_confirmation" if pending else "executed",
                    "actions": [{**a, "status": "pending" if pending else "sent"} for a in payload["actions"]]}
            return HTTPResult(200 if duplicate else 202, {**self.decisions[key], "duplicate": duplicate})
        if path == "/ai/device-states":
            return HTTPResult(200, {"items": deepcopy(self.devices)})
        if path.startswith("/ai/decisions/"):
            key = path.rsplit("/", 1)[1]
            return HTTPResult(200, deepcopy(self.decisions[key])) if key in self.decisions else HTTPResult(404, {})
        if path == "/voice/commands?status=thinking":
            return HTTPResult(200, {"items": deepcopy(self.recover), "total": len(self.recover)})
        if path == "/voice/commands?limit=10":
            return HTTPResult(200, {"items": deepcopy(self.old_commands), "total": len(self.old_commands)})
        if path == "/weather":
            return HTTPResult(200, self.weather)
        if path == "/sensing/results/latest":
            return HTTPResult(200, self.presence)
        if path.startswith("/sensing/results?"):
            return HTTPResult(200, {"items": self.sensing})
        return HTTPResult(404, {})


@pytest.fixture
def voice(tmp_path):
    settings = load_settings(environ={"HOMEVIS_VOICE_ENABLED": "true"}, mode="mock", data_dir=tmp_path)
    settings = replace(settings, integration=replace(settings.integration, allowed_lateness=0, async_alerts=True),
                       mqtt=replace(settings.mqtt, join_wait_seconds=0))
    clock, llm = FakeClock(BASE), FakeLLM()
    transport = VoiceTransport(clock)
    service = AlertService(LLMMessageGenerator(), DryRunTTS(), tmp_path / "audio")
    runtime = IntegrationRuntime(settings.integration, BackendClient(settings.integration, transport), clock=clock,
                                 fall_alert_service=service, voice_config=settings.voice, voice_llm=llm)
    yield SimpleNamespace(runtime=runtime, voice=runtime.voice, settings=settings, clock=clock, llm=llm, backend=transport)
    runtime.close()


def pump(env, key="voice-1", states=("completed", "awaiting_confirmation", "failed", "expired")):
    for _ in range(1500):
        env.voice.tick(env.clock())
        row = env.voice.store.get(key)
        if row and row["status"] in states:
            return row
        time.sleep(.001)
    raise AssertionError(env.voice.store.get(key))


def submit(env, text="욕실 전등 켜줘", key="voice-1", labels=("control_request",), **fields):
    env.llm.responses.append(intent(text, labels, **fields))
    assert env.runtime.receive_voice_request(message(text, key, env.clock()))
    return pump(env, key)


def automation(env, *, user="default", action="turn_off", scenario="light_auto_off"):
    controller = env.runtime.controller
    service = controller.confidence_service
    features = {k: 1.0 if k != "feedback" else .5 for k in service.config.SCENARIO_WEIGHTS[scenario]}
    result = service.score(scenario=scenario, features=features, timestamp=env.clock(), device="light",
                           action_name=action, room="room", user_id=user, device_id="light-01")
    assert result.action is not None
    controller.automation_actions.append(result.action)
    env.runtime.collect_outputs(env.clock())
    row = next(r for r in env.runtime.outbox.rows() if r["source_id"] == "automation:" + result.action_id)
    env.runtime.outbox.update(row["source_id"], status="accepted", response={"actions": [
        {**row["payload"]["actions"][0], "status": "sent"}]})
    return result


@pytest.mark.parametrize("field,value", [("voiceId", ""), ("text", " "), ("text", "x" * 501),
    ("confidence", float("nan")), ("confidence", float("inf")), ("confidence", -1), ("confidence", 1.1),
    ("confidence", True), ("expiresAt", "2026-10-24T12:00:10"), ("expiresAt", iso_time(BASE)),
    ("recognizedAt", iso_time(BASE + 1)), ("source", 123), ("room", "kitchen")])
def test_invalid_request_fields(field, value):
    with pytest.raises((ValueError, TypeError)):
        request_message(message(**{field: value}), BASE)


def test_optional_stt_not_fabricated():
    raw = message()
    del raw["confidence"]
    assert "confidence" not in request_message(raw, BASE)


@pytest.mark.parametrize("label", sorted(INTENTS))
def test_all_intents_and_explicit_feedback(label):
    text = "너무 빨리 껐어" if label == "feedback" else "테스트 발화"
    llm = FakeLLM()
    llm.responses.append(intent(text, (label,)))
    assert IntentClassifier(llm).classify(text)["intents"] == [label]


@pytest.mark.parametrize("answer", ["", "```json\n{}\n```", "{}", '{"intents":["execute_now"]}',
    '{"confidence":NaN}', '{"intents":["feedback"]}'])
def test_malformed_classifier_output_is_rejected(answer):
    llm = FakeLLM()
    llm.responses.append(answer)
    with pytest.raises((ValueError, TypeError)):
        IntentClassifier(llm).classify("왜 껐어?")


@pytest.mark.parametrize("text,label", [("왜 화력을 줄였어?", "feedback"), ("앞으로 불을 너무 빨리 끄지 마", "feedback"),
    ("방에 들어오면 자동으로 불 켜줘", "control_request")])
def test_misclassified_question_or_future_request_cannot_train_or_control(text, label):
    llm = FakeLLM()
    llm.responses.append(intent(text, (label,)))
    with pytest.raises(ContractError):
        IntentClassifier(llm).classify(text)


@pytest.mark.parametrize("action,parameters", [("on", {}), ("off", {}), ("blink", {"durationSec": 10}), ("fadeout", {})])
def test_light_actions_require_backend_confirmation(voice, action, parameters):
    row = submit(voice, action=action, parameters=parameters)
    assert row["status"] == "awaiting_confirmation"
    assert row["payload"]["voiceId"] == "voice-1"
    assert row["payload"]["actions"][0] == {"device": "light", "deviceId": "light-00", "action": action, **parameters}
    assert row["payload"]["requiresConfirmation"] is True
    assert "reason" not in row["payload"]
    assert row["payload"]["confidence"] == .92
    assert voice.runtime.outbox.audits("fall_user_alert") == []
    assert not list(voice.settings.integration.data_dir.rglob("*.wav"))


def test_fan_does_not_broaden_automatic_device_routes(voice):
    row = submit(voice, "주방 환풍기 강풍으로", device="fan", room="kitchen", action="set_speed", parameters={"speed": "high"})
    assert row["payload"]["actions"][0]["deviceId"] == "fan-01"
    assert row["payload"]["requiresConfirmation"]
    from src.control.identifiers import DEVICES
    assert "fan" not in DEVICES


def test_stove_turn_on_without_explicit_level_and_safe_state_rejected(voice):
    row = submit(voice, "인덕션 켜줘", device="stove", room="kitchen", action="turn_on")
    assert not row["payload"]["actions"]
    assert "제어하지 않았습니다" in row["payload"]["announcement"]


@pytest.mark.parametrize("confidence", [None, .2])
def test_missing_or_low_stt_no_control(voice, confidence):
    voice.llm.responses.append(intent("욕실 전등 켜줘"))
    voice.runtime.receive_voice_request(message(confidence=confidence))
    row = pump(voice)
    assert row["payload"]["actions"] == []


def test_missing_stt_status_still_answers_without_inventing_stt(voice):
    text = "욕실 불 켜져 있어?"
    voice.llm.responses.append(intent(text, ("status_question",), query="device"))
    voice.runtime.receive_voice_request(message(text, confidence=None))
    row = pump(voice)
    assert "꺼짐" in row["payload"]["announcement"]
    assert row["analysis"]["stt_confidence"] is None
    assert row["analysis"]["confidence_basis"] == "intent_only_no_stt"
    assert row["payload"]["confidence"] == .96


@pytest.mark.parametrize("query,expected", [("weather", "기준"), ("presence", "주방"), ("voice_history", "이전 음성 명령이 없습니다")])
def test_backend_queries_use_verified_schemas(voice, query, expected):
    row = submit(voice, "지금 상태 알려줘", labels=("status_question",), query=query, device=None, room=None, action=None)
    assert expected in row["payload"]["announcement"]
    assert "room" not in row["payload"]
    assert not row["payload"]["actions"]


def test_unknown_or_stale_presence_does_not_invent_occupancy(voice):
    voice.backend.presence["validSec"] = 0
    row = submit(voice, "어디 있어?", labels=("status_question",), query="presence")
    assert row["payload"]["announcement"] == FALLBACK


def test_ambiguous_device_and_mixed_control_are_refused(voice):
    row = submit(voice, "불 켜줘", room=None)
    assert row["payload"]["actions"] == []
    row = submit(voice, "불 켜줘 왜 껐어", "voice-2", labels=("control_request", "explanation_question"))
    assert row["payload"]["actions"] == []


def test_emergency_blocks_light_and_stove_changes(voice):
    voice.runtime.outbox.latch_fall(BASE, "fall-test")
    row = submit(voice)
    assert not row["payload"]["actions"]
    row = submit(voice, "인덕션 꺼줘", "voice-2", device="stove", room="kitchen", action="turn_off")
    assert row["payload"]["actions"][0]["action"] == "turn_off"
    row = submit(voice, "괜찮아", "voice-3", labels=("confirmation",), device=None, room=None, action=None)
    assert not row["payload"]["actions"]
    assert voice.runtime.outbox.fall_incident() is not None


def test_policy_proposals_remain_inactive(voice):
    policy = policy_snapshot(voice.runtime)
    row = submit(voice, "앞으로 1분 뒤에 불 꺼줘", labels=("preference_change",),
                 action="off", parameters={"light_off_seconds": 60})
    proposals = voice.voice.instructions.recent("default")
    assert len(proposals) == 1 and proposals[0]["status"] == "proposed"
    assert proposals[0]["confirmed_at"] is None
    assert policy_snapshot(voice.runtime) == policy
    assert not row["payload"]["actions"] and not row["payload"]["requiresConfirmation"]
    assert voice.runtime.controller.feedback_storage.list_records() == []


def test_question_uses_historical_policy_no_learning_no_false_memory(voice):
    result = automation(voice)
    voice.runtime.config = replace(voice.runtime.config, light_off_seconds=70)
    row = submit(voice, "방 불 왜 껐어?", labels=("explanation_question",), room="room", action="turn_off")
    assert "30초" in row["payload"]["announcement"] and "70초" not in row["payload"]["announcement"]
    assert "사용자 지시" not in row["payload"]["announcement"]
    assert "물리적 실행 완료는 확인하지 못" in row["payload"]["announcement"]
    assert not voice.runtime.controller.feedback_storage.has_action(result.action_id)
    assert len(voice.llm.calls) == 1


@pytest.mark.parametrize("feedback_confidence,updated", [(.95, True), (.65, False), (.3, False)])
def test_actual_legacy_feedback_pipeline_thresholds_unchanged(voice, feedback_confidence, updated):
    result = automation(voice)
    text = "방 불 너무 빨리 껐어"
    voice.llm.responses.extend([intent(text, ("feedback",), room="room", action="turn_off"),
                               {"feedback": "too_sensitive", "reason": "explicit evaluation", "confidence": feedback_confidence}])
    voice.runtime.receive_voice_request(message(text))
    row = pump(voice)
    assert row["effect_status"] == ("weight_updated" if updated else "weight_not_updated")
    records = voice.runtime.controller.feedback_storage.list_records()
    assert records[-1]["action_id"] == result.action_id
    assert records[-1]["weight_updated"] == updated
    assert len(voice.llm.calls) == 2  # owner-thread service reuses prepared inference
    assert voice.runtime.controller.confidence_service.config.FEEDBACK_APPLY_THRESHOLD == .8


@pytest.mark.parametrize("kind", ["ambiguous", "other_user", "profile_mismatch", "unsent"])
def test_feedback_requires_unambiguous_compatible_sent_action(voice, kind):
    result = automation(voice, user="someone_else" if kind == "other_user" else "default")
    if kind == "ambiguous":
        automation(voice)
    if kind in {"profile_mismatch", "unsent"}:
        row = voice.runtime.outbox.rows()[0]
        if kind == "profile_mismatch":
            row["source"]["explanation"]["input_profile"] = "legacy"
            voice.runtime.outbox.db.execute("UPDATE decisions SET source=? WHERE source_id=?", (json.dumps(row["source"]), row["source_id"]))
            voice.runtime.outbox.db.commit()
        else:
            voice.runtime.outbox.update(row["source_id"], response={"actions": []})
    row = submit(voice, "방 불 너무 빨리 껐어", labels=("feedback",), room="room", action="turn_off")
    assert row["effect_status"] is None
    assert not voice.runtime.controller.feedback_storage.has_action(result.action_id)
    assert len(voice.llm.calls) == 1


def test_bare_praise_never_selects_latest_action(voice):
    automation(voice)
    row = submit(voice, "잘했어", labels=("feedback",), device=None, room=None, action=None)
    assert row["effect_status"] is None and "학습하지 않았습니다" in row["payload"]["announcement"]


def test_explicit_explanation_focus_can_ground_followup_praise(voice):
    automation(voice)
    submit(voice, "방 불 왜 껐어", labels=("explanation_question",), room="room", action="turn_off")
    voice.llm.responses.extend([intent("잘했어", ("feedback",), device=None, room=None, action=None),
                               {"feedback": "positive", "confidence": .95, "reason": "explicit praise"}])
    voice.runtime.receive_voice_request(message("잘했어", "voice-2"))
    assert pump(voice, "voice-2")["effect_status"] == "weight_updated"


def test_mixed_question_and_feedback_both_processed(voice):
    automation(voice)
    text = "방 불 왜 껐어? 너무 빨리 껐잖아"
    voice.llm.responses.extend([intent(text, ("explanation_question", "feedback"), room="room", action="turn_off"),
                               {"feedback": "too_sensitive", "confidence": .95, "reason": "explicit evaluation"}])
    voice.runtime.receive_voice_request(message(text))
    row = pump(voice)
    assert row["effect_status"] == "weight_updated"
    assert "가중치에 반영" in row["payload"]["announcement"] and "30초" in row["payload"]["announcement"]


def test_qos_duplicate_recovery_and_restart_keep_identity(voice):
    row = submit(voice)
    assert not voice.runtime.receive_voice_request(message())
    assert not voice.runtime.receive_voice_request(message(text="다른 문장"))
    voice.voice.close()
    from src.interaction.coordinator import VoiceCoordinator
    restored = VoiceCoordinator(voice.runtime, voice.settings.voice, voice.runtime.shared_llm)
    voice.runtime.voice = voice.voice = restored
    voice.backend.recover = [{**message(), "status": "thinking"}]
    restored.next_recovery = 0
    for _ in range(20):
        restored.tick(voice.clock())
        time.sleep(.001)
    assert restored.store.get("voice-1")["decision_id"] == row["decision_id"]
    assert len([c for c in voice.backend.calls if c[0] == "POST"]) == 1
    assert len(voice.llm.calls) == 1


def test_restart_ambiguous_feedback_claim_prevents_double_learning(voice):
    result = automation(voice)
    assert voice.voice.store.claim_feedback(result.action_id, "prior-crashed-voice")
    text = "방 불 너무 빨리 껐어"
    voice.llm.responses.extend([intent(text, ("feedback",), room="room", action="turn_off"),
                               {"feedback": "too_sensitive", "confidence": .95, "reason": "explicit"}])
    voice.runtime.receive_voice_request(message(text))
    row = pump(voice)
    assert "중복 학습하지" in row["payload"]["announcement"]
    assert not voice.runtime.controller.feedback_storage.has_action(result.action_id)


def test_retry_uses_exact_saved_body_and_finite_timeout(voice):
    voice.backend.fail_post = BackendError("simulated network", retryable=True)
    voice.llm.responses.append(intent("욕실 전등 켜줘"))
    voice.runtime.receive_voice_request(message())
    for _ in range(1000):
        voice.voice.tick(voice.clock())
        row = voice.voice.store.get("voice-1")
        if row["status"] == "pending" and row["attempts"] == 1:
            break
        time.sleep(.001)
    voice.clock.now += .3
    pump(voice)
    posts = [c for c in voice.backend.calls if c[0] == "POST"]
    assert len(posts) == 2 and posts[0][2] == posts[1][2]
    assert all(0 < c[3] <= 1.5 for c in voice.backend.calls)


def test_confirmation_status_polled_even_after_original_expiry_without_repost(voice):
    row = submit(voice)
    response = voice.backend.decisions[row["decision_id"]]
    response["status"] = "executed"
    response["actions"][0]["status"] = "sent"
    voice.clock.now += 15
    row = pump(voice, states=("completed",))
    assert row["response"]["status"] == "executed"
    assert len([c for c in voice.backend.calls if c[0] == "POST"]) == 1


def test_backend_404_not_retried_as_another_decision(voice):
    voice.backend.fail_post = BackendError("unknown voice", status_code=404)
    row = submit(voice)
    assert row["status"] == "failed" and row["attempts"] == 1


def test_slow_llm_does_not_block_core_and_late_output_is_discarded(voice):
    release, entered = Event(), Event()
    def slow():
        entered.set()
        release.wait(3)
        return intent("욕실 전등 켜줘")
    voice.llm.responses.append(slow)
    voice.runtime.receive_voice_request(message())
    voice.voice.tick(voice.clock())
    assert entered.wait(1)
    try:
        voice.clock.now += 5.1
        started = time.monotonic()
        voice.runtime.run_once(voice.clock())
        assert time.monotonic() - started < .5
        row = pump(voice)
        assert row["payload"]["actions"] == [] and row["payload"]["announcement"] == FALLBACK
        release.set()
        time.sleep(.01)
        voice.voice.tick(voice.clock())
        assert len([c for c in voice.backend.calls if c[0] == "POST"]) == 1
    finally:
        release.set()


def test_expired_request_never_calls_llm_or_posts(voice):
    assert not voice.runtime.receive_voice_request(message(expiresAt=iso_time(BASE)))
    assert voice.llm.calls == []
    assert voice.backend.calls == []


def test_expiry_rechecked_in_http_worker(voice):
    raw = {"decisionId": "d", "voiceId": "v", "scenario": "voice_command", "confidence": .8,
           "announcement": "만료", "actions": [], "timestamp": iso_time(BASE), "expiresAt": iso_time(BASE)}
    with pytest.raises(TimeoutError):
        voice.voice.backend.post(raw)
    assert voice.backend.calls == []


def test_mqtt_router_utf8_retained_malformed_and_duplicate(voice):
    router = InputRouter(voice.settings.mqtt, voice.runtime)
    raw = json.dumps(message(), ensure_ascii=False).encode("utf-8")
    topic = voice.settings.mqtt.voice_topic
    router.accept(Incoming(topic, raw, BASE, True))
    router.accept(Incoming(topic, b"not-json", BASE))
    router.accept(Incoming(topic, b'{"confidence":NaN}', BASE))
    assert voice.voice.store.get("voice-1") is None
    router.accept(Incoming(topic, raw, BASE))
    router.accept(Incoming(topic, raw, BASE))
    assert len(voice.voice.store.rows("received")) == 1
    assert voice.llm.calls == []  # callbacks/router only enqueue


def test_http_sensing_and_mqtt_voice_share_host_router(voice):
    sensing = BackendSensingSource(voice.settings, voice.runtime.client, clock=voice.clock)
    class FakeSource:
        connection_generation = 1
        def drain(self, limit=200):
            return [Incoming(voice.settings.mqtt.voice_topic, json.dumps(message()).encode(), BASE)]
        def health(self):
            return {}
        def close(self):
            pass
    source = CombinedSource(sensing, FakeSource())
    router = InputRouter(voice.settings.mqtt, voice.runtime)
    try:
        for incoming in source.drain():
            router.accept(incoming)
        assert voice.voice.store.get("voice-1") is not None
    finally:
        source.close()


def test_persistent_mqtt311_client_and_qos_subscription(voice):
    pytest.importorskip("paho.mqtt.client")
    source = MQTTSource(voice.settings.mqtt, voice_only=True)
    try:
        assert source.client._clean_session is False
        assert int(source.client._protocol) == 4
        calls = []
        client = SimpleNamespace(subscribe=lambda topics: (calls.append(topics) or (0, 1)))
        source._connect(client, None, None, 0, None)
        source._connect(client, None, None, 0, None)
        assert calls == [[("home/voice/request", 1)], [("home/voice/request", 1)]]
        assert source.connection_generation == 2
    finally:
        source.close()


def test_voice_default_disabled_and_env_opt_in(tmp_path):
    settings = load_settings(environ={}, mode="mock", data_dir=tmp_path)
    assert not settings.voice.enabled and not settings.mqtt.voice_topic
    settings = load_settings(environ={"HOMEVIS_VOICE_ENABLED": "true", "HOMEVIS_VOICE_TOPIC": "home/voice/request"}, data_dir=tmp_path)
    assert settings.voice.enabled and settings.mqtt.voice_topic == "home/voice/request"
    with pytest.raises(ValueError):
        load_settings(environ={"HOMEVIS_VOICE_ENABLED": "perhaps"}, data_dir=tmp_path)


def test_shared_llm_lazy_single_initialization_and_prepared_no_inference():
    calls = []
    fake = FakeLLM()
    fake.responses.extend(["one", "two"])
    shared = SharedLLM(lambda: calls.append("created") or fake)
    assert calls == []
    assert shared.generate("s", "u") == "one"
    assert shared.generate("s", "v") == "two"
    with shared.prepared(["s", "cached", "answer"]):
        assert shared.generate("s", "cached") == "answer"
        with pytest.raises(RuntimeError):
            shared.generate("s", "wrong")
    assert calls == ["created"] and len(fake.calls) == 2


def test_shared_api_timeout_uses_same_client_pool():
    options = []
    class Client:
        def with_options(self, **kwargs):
            options.append(kwargs)
            return self
    class Adapter:
        name = "gpt"
        client = Client()
        def generate(self, system_prompt, user_prompt):
            return "answer"
    adapter = Adapter()
    shared = SharedLLM(lambda: adapter, clock=lambda: BASE)
    with shared.deadline(BASE + 2):
        assert shared.generate("s", "u") == "answer"
    assert options == [{"timeout": 2, "max_retries": 0}]
    assert shared._adapter is adapter


@pytest.mark.parametrize("state,action_status", [("awaiting_confirmation", "pending"), ("executed", "sent"), ("cancelled", "cancelled")])
def test_response_contract_states(voice, state, action_status):
    row = submit(voice)
    response = deepcopy(row["response"])
    response.update(status=state, duplicate=True)
    response["actions"][0]["status"] = action_status
    assert decision_response(200, response, row["payload"])["status"] == state
    response["actions"][0]["status"] = "fake_ack"
    with pytest.raises(ContractError):
        decision_response(200, response, row["payload"])


@pytest.mark.parametrize("action", [
    {"device": "light", "deviceId": "unverified", "action": "on", "extra": 1},
    {"device": "stove", "deviceId": "induction-01", "action": "set_level", "level": 10},
    {"device": "water_purifier", "deviceId": "water-01", "action": "dispense", "amountMl": 2001},
    {"device": "fan", "deviceId": "fan-01", "action": "set_speed", "speed": "maximum"},
    {"device": "light", "action": "on"}])
def test_action_parameters_are_strict(action):
    with pytest.raises(ContractError):
        action_payload(action)


def kitchen_ready(env):
    for offset in (0, 6):
        env.clock.now = BASE + offset
        for device in env.backend.devices:
            device["updatedAt"] = iso_time(env.clock())
        env.runtime.ingest_device_states({"items": env.backend.devices})
        env.runtime.ingest_location({"time": iso_time(env.clock()), "location": "kitchen", "location_confidence": .95})
        env.runtime.advance(env.clock())


@pytest.mark.parametrize("ready,amount", [(True, 250), (False, 250), (True, 2001)])
def test_water_requires_ready_device_and_bounded_amount(voice, ready, amount):
    kitchen_ready(voice)
    water = next(d for d in voice.backend.devices if d["device"] == "water_purifier")
    water["current_state"]["status"] = "idle" if ready else "dispensing"
    # Equal/newer cache must also agree; ingestion remains the existing state path.
    voice.runtime.devices.pop("water_purifier", None)
    row = submit(voice, "물 250밀리리터 줘", device="water_purifier", room="kitchen", action="dispense", parameters={"amountMl": amount})
    assert bool(row["payload"]["actions"]) == (ready and amount <= 2000)
    if row["payload"]["actions"]:
        assert row["payload"]["requiresConfirmation"]


@pytest.mark.parametrize("temperature,safe", [(120, True), (250, False), (None, False)])
def test_stove_level_change_needs_safe_current_temperature(voice, temperature, safe):
    kitchen_ready(voice)
    stove = next(d for d in voice.backend.devices if d["device"] == "stove")
    stove["current_state"]["temperature"] = temperature
    voice.runtime.devices.pop("stove", None)
    row = submit(voice, "화력 4단계로", device="stove", room="kitchen", action="set_level", parameters={"level": 4})
    assert bool(row["payload"]["actions"]) == safe


def test_restore_does_not_accept_ownership_without_prior_homevis_reduction(voice):
    kitchen_ready(voice)
    stove = next(d for d in voice.backend.devices if d["device"] == "stove")
    stove.update(control_state="homevis")
    stove["current_state"]["level"] = 4
    row = submit(voice, "원래 화력으로 복구해줘", device="stove", room="kitchen", action="restore_power")
    assert not row["payload"]["actions"]


def test_restore_reuses_original_safety_guard(voice):
    kitchen_ready(voice)
    voice.runtime.outbox.set_metadata("stove_reduction", {"requested_at": BASE, "accepted_at": BASE,
        "previous_level": 5, "requested_level": 4})
    stove = next(d for d in voice.backend.devices if d["device"] == "stove")
    stove.update(control_state="homevis")
    stove["current_state"]["level"] = 4
    voice.clock.now += 1
    stove["updatedAt"] = iso_time(voice.clock())
    voice.runtime.ingest_device_states({"items": voice.backend.devices})
    # Evaluate the latest appliance without creating any real control request.
    voice.runtime.advance(voice.clock())
    row = submit(voice, "원래 화력으로 복구해줘", device="stove", room="kitchen", action="restore_power")
    assert row["payload"]["actions"][0]["action"] == "restore_power"


def test_http_recovery_processes_unexpired_thinking_once(voice):
    voice.backend.recover = [{**message(), "status": "thinking", "decisionId": None}]
    voice.llm.responses.append(intent("욕실 전등 켜줘"))
    row = pump(voice)
    assert row["status"] == "awaiting_confirmation"
    voice.voice.reconnect()
    for _ in range(20):
        voice.voice.tick(voice.clock())
        time.sleep(.001)
    assert len(voice.llm.calls) == 1


def test_persisted_sending_body_restored_unchanged(voice):
    row = submit(voice)
    voice.voice.store.update(row["voice_id"], status="sending", response=None, next_attempt=0)
    voice.voice.close()
    from src.interaction.coordinator import VoiceCoordinator
    voice.voice = voice.runtime.voice = VoiceCoordinator(voice.runtime, voice.settings.voice, voice.runtime.shared_llm)
    restored = pump(voice)
    posts = [c[2] for c in voice.backend.calls if c[0] == "POST"]
    assert posts == [row["payload"], row["payload"]]
    assert restored["response"]["duplicate"] is True


def test_control_refused_when_latest_state_changes_before_post(voice):
    from src.interaction.control import validate_safety
    kitchen_ready(voice)
    stove = next(d for d in voice.backend.devices if d["device"] == "stove")
    previous = deepcopy(stove)
    stove["updatedAt"] = iso_time(voice.clock() + .1)
    stove["current_state"]["temperature"] = 250
    voice.clock.now += .1
    voice.runtime.ingest_device_states({"items": voice.backend.devices})
    with pytest.raises(ContractError):
        validate_safety(voice.runtime, {"device": "stove", "deviceId": "induction-01", "action": "set_level", "level": 4}, previous, voice.clock())


def test_queue_capacity_and_late_queued_work_do_not_execute(voice):
    voice.voice.config = replace(voice.voice.config, queue_size=1)
    assert voice.voice.receive(message())
    assert not voice.voice.receive(message(key="voice-2"))
    voice.clock.now += 10
    voice.voice.tick(voice.clock())
    assert voice.voice.store.get("voice-1")["status"] == "expired"
    assert not voice.llm.calls


def test_completed_feedback_is_not_learned_again_after_restart(voice):
    result = automation(voice)
    text = "방 불 너무 빨리 껐어"
    voice.llm.responses.extend([intent(text, ("feedback",), room="room", action="turn_off"),
                               {"feedback": "too_sensitive", "confidence": .95, "reason": "explicit"}])
    voice.voice.receive(message(text))
    assert pump(voice)["effect_status"] == "weight_updated"
    voice.voice.close()
    from src.interaction.coordinator import VoiceCoordinator
    voice.voice = voice.runtime.voice = VoiceCoordinator(voice.runtime, voice.settings.voice, voice.runtime.shared_llm)
    assert not voice.voice.receive(message(text))
    voice.llm.responses.extend([intent(text, ("feedback",), room="room", action="turn_off"),
                               {"feedback": "too_sensitive", "confidence": .95, "reason": "explicit"}])
    voice.voice.receive(message(text, "voice-2"))
    row = pump(voice, "voice-2")
    assert row["effect_status"] is None
    assert len([r for r in voice.runtime.controller.feedback_storage.list_records() if r["action_id"] == result.action_id]) == 1


def test_mock_runtime_never_initializes_paid_factory_even_if_voice_enabled(tmp_path, monkeypatch):
    monkeypatch.setattr("src.integration.runtime.create_llm", lambda: (_ for _ in ()).throw(AssertionError("paid factory")))
    settings = load_settings(environ={"HOMEVIS_VOICE_ENABLED": "true"}, mode="mock", data_dir=tmp_path)
    clock = FakeClock(BASE)
    client = BackendClient(settings.integration, VoiceTransport(clock))
    runtime = IntegrationRuntime(settings.integration, client, voice_config=settings.voice, clock=clock)
    try:
        assert runtime.shared_llm._loaded is False
        runtime.voice.receive(message())
        row = pump(SimpleNamespace(voice=runtime.voice, clock=clock))
        assert row["payload"]["actions"] == []
        assert runtime.shared_llm._adapter is None
    finally:
        runtime.close()


def test_voice_wire_models_against_verified_backend_checkout(voice):
    """Optional offline cross-repository check, pinned to the inspected backend v0.6."""
    import os
    import subprocess
    import sys
    from types import ModuleType
    checkout = os.environ.get("HOMEVIS_BACKEND_CHECKOUT")
    if not checkout:
        pytest.skip("optional: set HOMEVIS_BACKEND_CHECKOUT for pinned v0.6 schema validation")
    pytest.importorskip("pydantic")
    source = subprocess.run(["git", "show", "00e59be71050bb5c4081ecd19f912d42f4abb2f0:app/schemas.py"],
                            cwd=checkout, capture_output=True, encoding="utf-8", check=True).stdout
    module = ModuleType("homevis_voice_backend_v06")
    sys.modules[module.__name__] = module
    try:
        exec(compile(source, "verified_backend_v06_schemas.py", "exec"), module.__dict__)
        row = submit(voice)
        parsed = module.AiDecisionRequest.model_validate(row["payload"])
        assert parsed.requiresConfirmation and parsed.voiceId == "voice-1"
        response = module.AiDecisionAccepted.model_validate(row["response"]).model_dump()
        assert decision_response(202, response, row["payload"])["status"] == "awaiting_confirmation"
        recovery = module.VoiceCommandListResponse.model_validate({"items": [
            {**message(), "status": "thinking", "updatedAt": iso_time(BASE)}], "total": 1}).model_dump()
        assert command_list(recovery, BASE)[0]["voiceId"] == "voice-1"
        no_room = {**row["payload"], "actions": [], "requiresConfirmation": False}
        no_room.pop("room")
        assert module.AiDecisionRequest.model_validate(no_room).room is None
    finally:
        sys.modules.pop(module.__name__, None)


@pytest.mark.parametrize("active,expected", [(False, False), (True, True)])
def test_explanation_only_attributes_verified_historical_instruction(voice, active, expected):
    automation(voice)
    record = voice.voice.explanations.candidates(BASE)[0]
    record["source"]["snapshot"]["instruction_id"] = "historic-instruction"
    instruction = {"instruction_id": "historic-instruction", "user_id": "default",
                   "confirmed_at": BASE - 5 if active else None, "effective_from": BASE - 5 if active else None,
                   "status": "active" if active else "proposed"}
    # Historical fixture only: production exposes no long-term activation API.
    response = ExplanationService.explain(record, instruction)
    assert ("사용자 지시" in response) is expected
    instruction["instruction_id"] = "different-instruction"
    assert "사용자 지시" not in ExplanationService.explain(record, instruction)


def test_voice_receive_failure_isolated_from_sensing(voice, monkeypatch):
    def fail(*args):
        raise RuntimeError("private content must not enter diagnostic")
    monkeypatch.setattr(voice.voice, "receive", fail)
    router = InputRouter(voice.settings.mqtt, voice.runtime)
    router.accept(Incoming(voice.settings.mqtt.voice_topic, json.dumps(message()).encode(), BASE))
    assert voice.runtime.diagnostics[-1] == {"code": "voice_receive_failed", "error": "RuntimeError"}
    assert voice.runtime.ingest_location({"time": iso_time(BASE), "location": "room", "location_confidence": .95})
    voice.runtime.advance(BASE)
    assert voice.runtime.last_decision is not None


def test_explanation_metadata_failure_cannot_drop_core_decision(voice, monkeypatch):
    def fail(*args):
        raise ValueError("invalid optional historical metadata")
    monkeypatch.setattr("src.interaction.explanation.decision_snapshot", fail)
    result = automation(voice)
    row = voice.runtime.outbox.rows()[0]
    assert row["source"]["snapshot_error"] == "ValueError"
    assert row["source"]["action_id"] == result.action_id
    assert row["payload"]["actions"]


def test_unverified_id_and_failed_status_poll_never_execute(voice):
    row = submit(voice)
    voice.backend.decisions.clear()
    voice.clock.now += 2
    for _ in range(20):
        voice.voice.tick(voice.clock())
        time.sleep(.001)
    state = voice.voice.store.get(row["voice_id"])
    assert state["status"] == "awaiting_confirmation" and state["error"].startswith("status_unavailable:")
    assert len([c for c in voice.backend.calls if c[0] == "POST"]) == 1


@pytest.mark.parametrize("changed", ["same_time_conflict", "moved_room"])
def test_control_conflicting_snapshot_or_moved_target_is_rejected(voice, changed):
    from src.interaction.control import validate_safety
    kitchen_ready(voice)
    original = deepcopy(next(d for d in voice.backend.devices if d["device"] == "water_purifier"))
    cached = voice.runtime.devices["water_purifier"]
    if changed == "same_time_conflict":
        original["current_state"]["status"] = "dispensing"
    else:
        newer = deepcopy(cached.raw)
        newer["room"] = "room"
        newer["updatedAt"] = iso_time(voice.clock() + .1)
        voice.runtime.devices["water_purifier"] = replace(cached, raw=newer, measured_at=voice.clock() + .1)
        voice.clock.now += .1
    with pytest.raises(ContractError):
        validate_safety(voice.runtime, {"device": "water_purifier", "deviceId": "water-01", "action": "dispense", "amountMl": 250}, original, voice.clock())


def test_persistent_old_sensing_subscription_does_not_duplicate_http_input(voice):
    pytest.importorskip("paho.mqtt.client")
    source = MQTTSource(voice.settings.mqtt, voice_only=True)
    try:
        source._message(None, None, SimpleNamespace(topic=voice.settings.mqtt.location_topic,
            payload=b'{}', retain=False))
        assert source.rejected == 1 and list(source.drain()) == []
        source._message(None, None, SimpleNamespace(topic=voice.settings.mqtt.voice_topic,
            payload=json.dumps(message()).encode(), retain=False))
        assert len(list(source.drain())) == 1
    finally:
        source.close()


def test_hallucinated_feedback_target_does_not_turn_praise_into_learning(voice):
    result = automation(voice)
    # Valid JSON and high confidence are not proof that the user identified light/off.
    row = submit(voice, "잘했어", labels=("feedback",), room="room", action="turn_off")
    assert row["effect_status"] is None
    assert not voice.runtime.controller.feedback_storage.has_action(result.action_id)
    assert len(voice.llm.calls) == 1


def test_hallucinated_room_cannot_disambiguate_two_feedback_targets(voice):
    automation(voice)
    records = voice.voice.explanations.candidates(BASE)
    second = deepcopy(records[0])
    second["payload"]["room"] = "toilet"
    second["source_id"] = "automation:another-action"
    text = "불 너무 빨리 껐어"
    proposal = intent(text, ("feedback",), room="room", action="turn_off")
    assert ExplanationService.resolve(proposal, records + [second], feedback_text=text) is None
