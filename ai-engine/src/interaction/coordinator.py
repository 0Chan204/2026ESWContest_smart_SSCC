"""Owner-thread orchestration; bounded inference and HTTP lanes never touch controller/DB."""
from copy import deepcopy

from src.control.feedback.natural_language_interpreter import NaturalLanguageFeedbackInterpreter
from src.control.feedback.natural_language_service import NaturalLanguageFeedbackService
from src.integration.backend_client import BackendError
from src.integration.schemas import ContractError, iso_time, measured_time
from src.llm.prompts import FEEDBACK_INTERPRETATION_SYSTEM_PROMPT, build_feedback_interpretation_prompt
from .backend import VoiceBackend
from .contracts import REQUEST_FIELDS, request_message, decision_payload
from .control import propose_control, validate_safety
from .explanation import ExplanationService, policy_snapshot
from .intent import IntentClassifier
from .response import VoiceResponseService, FALLBACK
from .storage import VoiceStore, UserInstructionStorage
from .worker import Worker


class VoiceCoordinator:
    def __init__(self, runtime, config, llm):
        self.runtime, self.config, self.llm = runtime, config, llm
        self.clock = runtime.clock
        self.backend = VoiceBackend(runtime.client, config, self.clock)
        self.store = VoiceStore(runtime.outbox)
        self.instructions = UserInstructionStorage(self.store)
        self.explanations = ExplanationService(runtime, self.instructions, config)
        self.classifier = IntentClassifier(llm)
        self.work = Worker("homevis-voice-inference")
        self.http = Worker("homevis-voice-http")
        self.work_job = self.http_job = None
        self.next_recovery = 0

    def close(self):
        self.work.close()
        self.http.close()

    def health(self):
        counts = {r[0]: r[1] for r in self.store.db.execute("SELECT status,count(*) FROM voice_requests GROUP BY status")}
        return {"enabled": True, "counts": counts, "inference_busy": self.work_job is not None,
                "http_busy": self.http_job is not None}

    def receive(self, raw, received_at=None):
        now = self.clock()
        try:
            request = request_message(raw, now)
            return self.store.receive(request, now if received_at is None else received_at, self.config.queue_size)
        except (ValueError, TypeError, KeyError):
            self.runtime.diagnostic("voice_request_rejected")
            return False

    def reconnect(self):
        self.next_recovery = 0

    def _infer(self, row, records, focus, deadline):
        request = row["request"]
        with self.llm.deadline(deadline):
            intent = self.classifier.classify(request["text"])
            if intent["confidence"] < self.config.min_intent_confidence:
                raise ContractError("intent confidence insufficient")
            if request.get("confidence") is not None and request["confidence"] < self.config.min_stt_confidence:
                raise ContractError("STT confidence insufficient")
            facts = {}
            labels = intent["intents"]
            if "control_request" in labels or "status_question" in labels:
                query = intent["query"] or "device"
                if "control_request" in labels or query == "device":
                    facts["devices"] = self.backend.devices(deadline)
                elif query == "weather":
                    facts["weather"] = self.backend.weather(deadline)
                elif query == "presence":
                    facts["presence"] = self.backend.presence(deadline)
                elif query == "voice_history":
                    facts["commands"] = self.backend.commands(deadline=deadline)
            if "explanation_question" in labels and intent["device"] == "air_purifier":
                facts["devices"] = self.backend.devices(deadline)
            target = ExplanationService.resolve(intent, records, focus,
                feedback_text=request["text"] if "feedback" in labels else None)
            prepared = None
            if ("feedback" in labels and target and target.get("feedback_eligible")
                    and request.get("confidence") is not None):
                history = target["history"]
                context = NaturalLanguageFeedbackService._action_context(history, history["action"])
                user_prompt = build_feedback_interpretation_prompt(context, request["text"].strip())
                raw = self.llm.generate(FEEDBACK_INTERPRETATION_SYSTEM_PROMPT, user_prompt)
                NaturalLanguageFeedbackInterpreter(self.llm, max_retries=0)._parse(raw)
                prepared = [FEEDBACK_INTERPRETATION_SYSTEM_PROMPT, user_prompt, raw]
        return {"intent": intent, "facts": facts, "target": target, "prepared_feedback": prepared}

    def _finish_inference(self, row, result, now):
        intent, facts = result["intent"], result["facts"]
        labels, target = intent["intents"], result["target"]
        parts, actions, room, control_device = [], [], None, None
        if "explanation_question" in labels:
            if intent["query"] == "policy":
                policy = policy_snapshot(self.runtime)["policy"]
                parts.append(f"현재 설정은 주방 이탈 {policy['automation_absence_seconds']:g}초, 복귀 {policy['automation_return_seconds']:g}초, "
                             f"전등 켜기 {policy['light_on_seconds']:g}초, 끄기 {policy['light_off_seconds']:g}초이며 신뢰도와 안전 조건도 확인합니다.")
                proposals = self.instructions.recent(self.config.user_id)
                if proposals:
                    parts.append("저장된 사용자 설정 요청은 아직 제안 상태이며 자동 적용되지 않았습니다.")
            else:
                instruction_id = (target or {}).get("source", {}).get("snapshot", {}).get("instruction_id")
                instruction = self.instructions.get(instruction_id) if instruction_id else None
                if intent["device"] == "air_purifier":
                    parts.append(self.explanations.explain_purifier(target, facts.get("devices", []), now))
                else:
                    parts.append(self.explanations.explain(target, instruction))
                if target:
                    self.runtime.outbox.set_metadata("voice_focus", {"source_id": target["source_id"],
                        "user_id": self.config.user_id, "until": now + 60})
        if "status_question" in labels:
            parts.append(VoiceResponseService.status(intent, facts, now, self.runtime.config.device_max_age, row["voice_id"]))
        if "control_request" in labels:
            try:
                action, control_device = propose_control(intent, facts.get("devices", []), row["request"], self.runtime, self.config, now)
                actions, room = [action], control_device["room"]
                parts.append("인덕션 끄기를 백엔드에 요청합니다. 실제 꺼짐은 상태 보고로 확인해야 합니다."
                             if action["device"] == "stove" and action["action"] == "turn_off" else
                             "요청한 기기 동작은 아직 실행하지 않았습니다. 백엔드 확인 화면에서 승인해 주세요.")
            except (ValueError, TypeError, KeyError):
                parts.append("기기 대상이나 안전 조건을 확인하지 못해 제어하지 않았습니다. 구역과 동작을 확인해 주세요.")
        if "control_instruction" in labels or "preference_change" in labels:
            self.instructions.propose(row["request"], intent, self.config.user_id,
                                      policy_snapshot(self.runtime)["policy_version"], now)
            parts.append("설정 요청을 제안 상태로 저장했습니다. 장기 설정 승인 기능이 연결되기 전에는 실제 자동화 기준을 변경하지 않습니다.")
        if "feedback" in labels:
            parts.append(self._feedback(row, result))
        if "confirmation" in labels:
            parts.append(VoiceResponseService.confirmation())
        if "general_question" in labels:
            parts.append("기기 상태, 재실, 날씨, 이전 제어 이유와 설정 요청을 도와드릴 수 있습니다. 원하시는 항목을 말씀해 주세요.")
        if not parts or "unknown" in labels:
            parts.append(FALLBACK)
        confidence = intent["confidence"]
        stt = row["request"].get("confidence")
        if stt is not None:
            confidence = min(confidence, stt)
        # Separate diagnostic values; never overwrite central confidence or pretend
        # this minimum is a calibrated probability of physical execution.
        analysis = {"intent": intent, "stt_confidence": stt, "intent_confidence": intent["confidence"],
                    "confidence_basis": "min_stt_intent" if stt is not None else "intent_only_no_stt",
                    "action_id": (target or {}).get("history", {}).get("action_id"),
                    "control_device": control_device}
        self._prepare(row, " ".join(parts)[:500], now, confidence, actions, room, analysis)

    def _feedback(self, row, result):
        target = result["target"]
        prepared = result["prepared_feedback"]
        if not target or not prepared or not self.explanations.eligible_feedback(target):
            return "어떤 자동 제어에 대한 평가인지 확실하지 않아 학습하지 않았습니다. 기기와 동작을 알려 주세요."
        controller = self.runtime.controller
        action_id = target["history"]["action_id"]
        current = controller.decision_history.get(action_id)
        if (current != target["history"] or controller.user_id != self.config.user_id
                or controller.feedback_storage.has_action(action_id)):
            return "사용자·판단 기록이 맞지 않거나 이미 반영된 의견이어서 다시 학습하지 않았습니다."
        if not self.store.claim_feedback(action_id, row["voice_id"]):
            return "이미 처리했거나 처리 결과 확인이 필요한 의견이어서 중복 학습하지 않았습니다."
        self.store.update(row["voice_id"], effect_status="feedback_started")
        with self.llm.prepared(prepared):
            outcome = controller.apply_natural_language_feedback(action_id, row["request"]["text"], user_id=self.config.user_id)
        updated = outcome.get("weight_updated") is True
        self.store.update(row["voice_id"], effect_status="weight_updated" if updated else "weight_not_updated")
        with self.store.db:
            self.store.db.execute("UPDATE voice_feedback_claims SET status=? WHERE action_id=?",
                                  ("applied" if updated else "not_applied", action_id))
        return ("말씀하신 평가를 기존 학습 기준에 따라 가중치에 반영했습니다." if updated else
                "말씀하신 평가를 확인했지만 기존 학습 기준을 충족하지 않아 가중치는 변경하지 않았습니다.")

    def _prepare(self, row, text, now, confidence=0.0, actions=None, room=None, analysis=None):
        if now >= row["expires_at"] - self.config.http_timeout:
            self.store.update(row["voice_id"], status="expired", error="insufficient_send_budget")
            return
        payload = {"decisionId": row["decision_id"], "voiceId": row["voice_id"], "scenario": "voice_command",
                   "confidence": confidence, "timestamp": iso_time(now), "expiresAt": row["request"]["expiresAt"],
                   "announcement": text, "actions": actions or [], "requiresConfirmation": bool(actions) and not all(
                       a["device"] == "stove" and a["action"] == "turn_off" for a in actions)}
        if room is not None:
            payload["room"] = room
        self.store.update(row["voice_id"], status="pending", payload=decision_payload(payload), analysis=analysis or {})
        for action in actions or []:
            self.runtime.home_automation.note_manual_control(action, now)

    def _finish_http(self, kind, row, future, now):
        try:
            result = future.result()
            if kind == "recovery":
                for command in result:
                    if command["status"] == "thinking" and not command.get("decisionId"):
                        self.receive({k: v for k, v in command.items() if k in REQUEST_FIELDS})
                return
            response = result.body if kind == "post" else result
            state = response["status"]
            local_status = "awaiting_confirmation" if state == "awaiting_confirmation" else (
                "expired" if state == "expired" else "completed")
            self.store.update(row["voice_id"], status=local_status, response=response,
                              next_attempt=now + self.config.status_interval, error=None)
        except Exception as exc:
            code = type(exc).__name__
            if kind == "recovery":
                self.runtime.diagnostic("voice_recovery_unavailable", error=code)
                return
            if kind == "status":
                # A failed GET never authorizes another POST, even after restart.
                self.store.update(row["voice_id"], error="status_unavailable:" + code,
                                  next_attempt=now + self.config.recovery_interval)
                return
            retry = isinstance(exc, BackendError) and exc.retryable and row["attempts"] < 3
            self.store.update(row["voice_id"], status="pending" if retry else "failed",
                              error="delivery_unknown:" + code, next_attempt=now + .25)

    def tick(self, now):
        if self.http_job and self.http_job[2].done():
            kind, row, future = self.http_job
            self.http_job = None
            self._finish_http(kind, row, future, now)
        if self.work_job:
            voice_id, deadline, future = self.work_job
            row = self.store.get(voice_id)
            if future.done():
                self.work_job = None
                if row["status"] == "processing":
                    try:
                        result = future.result()
                        if self.clock() >= deadline:
                            raise TimeoutError("voice inference deadline")
                        self._finish_inference(row, result, now)
                    except Exception as exc:
                        self.store.update(voice_id, error=type(exc).__name__)
                        self._prepare(row, FALLBACK, self.clock())
            elif now >= deadline and row["status"] == "processing":
                # Thread cannot be force-killed (local Qwen); late output is ignored,
                # no replacement worker is spawned, and the core loop keeps ticking.
                self.store.update(voice_id, error="inference_deadline")
                self._prepare(row, FALLBACK, now)
        for status in ("received", "pending"):
            for row in self.store.rows(status, self.config.queue_size):
                if now >= row["expires_at"] - self.config.http_timeout:
                    self.store.update(row["voice_id"], status="expired", error="voice_expired")
                elif status == "received" and now >= row["expires_at"] - self.config.send_margin:
                    self._prepare(row, FALLBACK, now)
        if self.work_job is None:
            rows = self.store.rows("received", 1)
            if rows:
                row = rows[0]
                deadline = min(row["expires_at"] - self.config.send_margin, now + self.config.llm_timeout)
                records = self.explanations.candidates(now)
                for record in records:
                    record["feedback_eligible"] = self.explanations.eligible_feedback(record)
                    if record["feedback_eligible"]:
                        original = self.runtime.controller.decision_history.get(record["history"]["action_id"])
                        if original == record["history"]:
                            # Preserve original JSON key order for the exact legacy
                            # prompt replay; the outbox uses a sorted serialization.
                            record["history"] = original
                        else:
                            record["feedback_eligible"] = False
                context = self.runtime.outbox.get_metadata("voice_focus") or {}
                focus = context.get("source_id") if context.get("user_id") == self.config.user_id and now < context.get("until", 0) else None
                self.store.update(row["voice_id"], status="processing")
                self.work_job = (row["voice_id"], deadline, self.work.submit(self._infer, deepcopy(row), deepcopy(records), focus, deadline))
        if self.http_job is None:
            for row in self.store.rows("pending", self.config.queue_size):
                if row["next_attempt"] > now:
                    continue
                try:
                    for action in row["payload"]["actions"]:
                        validate_safety(self.runtime, action, row["analysis"]["control_device"], now)
                except (ValueError, TypeError, KeyError):
                    self.store.update(row["voice_id"], status="failed", error="safety_changed_before_send")
                    continue
                self.store.update(row["voice_id"], status="sending", attempts=row["attempts"] + 1)
                row["attempts"] += 1
                self.http_job = ("post", row, self.http.submit(self.backend.post, row["payload"]))
                break
        if self.http_job is None:
            rows = self.store.rows("awaiting_confirmation", 1)
            if rows and now >= rows[0]["next_attempt"]:
                row = rows[0]
                self.http_job = ("status", row, self.http.submit(self.backend.status, row["payload"]))
            elif now >= self.next_recovery:
                self.next_recovery = now + self.config.recovery_interval
                self.http_job = ("recovery", None, self.http.submit(lambda: self.backend.commands(recovery=True)))
