"""Grounded explanations: immutable historical evidence, not present-day reconstruction."""
from dataclasses import asdict
from datetime import time
import hashlib
import json
import re

from src.integration.outbox import encode

POLICY_KEYS = ("automation_profile", "automation_absence_seconds", "automation_return_seconds",
               "light_on_seconds", "light_off_seconds", "stove_reduce_steps")


def policy_snapshot(runtime):
    policy = {key: getattr(runtime.config, key) for key in POLICY_KEYS}
    policy["confidence"] = asdict(runtime.controller.confidence_service.config)
    policy["safety"] = asdict(runtime.controller.realtime_engine.config)
    policy["home_automation"] = asdict(runtime.config.home_automation)
    policy["scenarios"] = {k: v.isoformat() if isinstance(v, time) else v
                           for k, v in asdict(runtime.controller.bedtime_light.config).items()}
    return {"policy": policy, "policy_version": hashlib.sha256(encode(policy).encode()).hexdigest()[:16],
            "instruction_id": None}  # Proposed instructions are NOT applied policies.


def decision_snapshot(runtime, output=None):
    engine = runtime.controller.realtime_engine
    realtime = None if runtime.last_decision is None else runtime.last_decision.to_dict()
    if realtime is not None:
        # The emitted action already references its scored history. Do not copy
        # unrelated per-tick UUIDs into the immutable scenario evidence.
        realtime.pop("confidence_decision", None)
    relevant_feedback = []
    if output is not None:
        from src.integration.schemas import measured_time
        for feedback in runtime.controller.feedback_storage.list_records():
            if (feedback.get("user_id") == runtime.controller.user_id and feedback.get("weight_updated")
                    and feedback.get("scenario") == getattr(output, "scenario", None)
                    and measured_time(feedback["timestamp"]) <= output.timestamp):
                relevant_feedback.append(feedback["action_id"])
    return {**policy_snapshot(runtime), "user_id": runtime.controller.user_id,
            "prior_feedback_action_ids": relevant_feedback[-10:],
            "sensing": None if engine._sensing is None else asdict(engine._sensing),
            "devices": {k: None if v is None else v.raw for k, v in runtime.evaluated_devices.items()},
            "realtime_decision": realtime}


class ExplanationService:
    def __init__(self, runtime, instructions, config):
        self.runtime, self.instructions, self.config = runtime, instructions, config

    def candidates(self, now):
        result = []
        for row in self.runtime.outbox.db.execute(
                "SELECT source_id,source,payload,response,status FROM decisions WHERE created_at>=? ORDER BY created_at DESC LIMIT 100",
                (now - self.config.history_seconds,)):
            record = {k: (json.loads(row[k]) if row[k] is not None and k in {"source", "payload", "response"} else row[k]) for k in row.keys()}
            source = record["source"]
            history = source.get("explanation") or {}
            owner = history.get("user_id", source.get("snapshot", {}).get("user_id"))
            if owner != self.config.user_id or not record["payload"] or (
                    not record["payload"]["actions"] and record["payload"]["scenario"] != "away_all_off"):
                continue
            record["history"] = history
            result.append(record)
        return result

    @staticmethod
    def resolve(intent, records, focus=None, feedback_text=None):
        # No 'latest action' heuristic. Without a named target, only a recent,
        # explicitly explained dialogue focus may resolve an elliptical utterance.
        device, room, action = (intent[k] for k in ("device", "room", "action"))
        if intent.get("query") == "away_all_off" and feedback_text is None:
            selected = [r for r in records if r["payload"]["scenario"] == "away_all_off"]
            return selected[0] if len(selected) == 1 else None
        if feedback_text is not None:
            # An LLM can hallucinate target fields even with a valid evidence quote.
            # In particular, '잘했어' must not turn into an invented light/off target.
            device_words = {"light": r"전등|조명|불", "stove": r"인덕션|화력|화구|레인지",
                            "water_purifier": r"정수기|출수|물", "fan": r"환풍기|환기팬", "air_purifier": r"공기청정기|공청기"}
            if device and not re.search(device_words[device], feedback_text):
                return None
            room_words = {"room": r"침실|방", "kitchen": r"주방|부엌", "toilet": r"욕실|화장실"}
            if room and not re.search(room_words[room], feedback_text):
                room = None
            action_words = {"turn_off": r"껐|꺼|끄|차단", "off": r"껐|꺼|끄|차단",
                            "turn_on": r"켰|켜|키|켜짐", "on": r"켰|켜|키|켜짐",
                            "reduce_power": r"줄|낮|감소", "restore_power": r"복구|돌려|원래",
                            "dispense": r"출수|물.*(?:줬|주|나왔)", "set_level": r"화력|단계"}
            if action and (action not in action_words or not re.search(action_words[action], feedback_text)):
                action = None
        if not device and not action:
            return next((r for r in records if r["source_id"] == focus
                         and (not room or r["payload"].get("room") == room)), None) if focus else None
        selected = []
        for record in records:
            actions = record["payload"]["actions"]
            if len(actions) != 1:
                continue
            actual = actions[0]
            source_action = record["source"].get("action", actual["action"])
            aliases = {"on": "turn_on", "off": "turn_off"}
            if device and actual["device"] != device:
                continue
            if room and record["payload"].get("room") != room:
                continue
            if action and aliases.get(source_action, source_action) != aliases.get(action, action):
                continue
            selected.append(record)
        return selected[0] if len(selected) == 1 else None

    @staticmethod
    def explain(record, instruction=None):
        if record is None:
            return "어느 기기의 어떤 제어를 말씀하시는지 알려 주세요. 관련 판단을 하나로 특정하지 못했습니다."
        source, history = record["source"], record["history"]
        snapshot = source.get("snapshot") or {}
        policy = snapshot.get("policy", {})
        basis = "시스템 자동화 규칙"
        if (instruction and instruction["instruction_id"] == snapshot.get("instruction_id")
                and instruction["user_id"] == snapshot.get("user_id")
                and instruction["confirmed_at"] is not None and instruction["effective_from"] is not None
                and instruction["effective_from"] <= source["timestamp"]
                and instruction["status"] in {"active", "superseded"}):
            basis = "당시 확인되어 적용 중이던 사용자 지시"
        scenario = source.get("scenario")
        if scenario in {"cooking_air_clean", "away_all_off"}:
            evidence = source.get("details", {})
            reason = (f"집 전체 부재가 설정된 {evidence.get('confirm_seconds', 600):g}초 이상 확인되어 외출 전체 OFF를 요청한 기록입니다."
                      if scenario == "away_all_off" else
                      "인덕션 상태와 공기청정기 상태에 따른 조리 연동으로 공기청정기 "
                      + ("켜기" if source.get("action") == "on" else "끄기") + "를 요청한 기록입니다.")
            return reason + (" 백엔드에 접수됐으며 물리적 동작 완료와는 다릅니다." if record.get("status") in {"accepted", "accepted_partial"}
                             else " 백엔드 접수는 아직 확인되지 않았습니다.")
        action_names = {"reduce_power": "화력 감소", "restore_power": "화력 복구", "turn_off": "끄기", "turn_on": "켜기"}
        name = action_names.get(source.get("action"), "기기 제어")
        key = {"stove_absence": "automation_absence_seconds", "stove_return": "automation_return_seconds",
               "light_auto_on": "light_on_seconds", "light_auto_off": "light_off_seconds"}.get(scenario)
        if source.get("action") == "reduce_power":
            key = "automation_absence_seconds"
        elif source.get("action") == "restore_power":
            key = "automation_return_seconds"
        period = f"당시 대기 기준 {policy[key]:g}초와 " if key in policy else ""
        observation = ""
        if source.get("action") == "reduce_power":
            absence = (snapshot.get("realtime_decision") or {}).get("kitchen_absence_seconds")
            if isinstance(absence, (int, float)) and absence >= 0:
                observation = f"기록된 주방 이탈 시간은 {absence:g}초입니다. "
        score = ""
        if history.get("confidence") is not None and history.get("threshold") is not None:
            score = f" (판단 점수 {history['confidence']:.2f}, 기준 {history['threshold']:.2f})"
        if snapshot.get("prior_feedback_action_ids"):
            score += "; 앞선 피드백 학습 이후 기록된 가중치를 사용했습니다"
        delivery = "백엔드 전달은 확인되지 않았습니다."
        response = record.get("response") or {}
        if any(a.get("status") == "sent" for a in response.get("actions", [])):
            delivery = "백엔드가 제어 명령 전송을 기록했지만 물리적 실행 완료는 확인하지 못했습니다."
        return f"{observation}{period}{basis}에 따라 {name}를 요청한 기록입니다{score}. {delivery}"

    def explain_purifier(self, record, devices, now):
        from src.integration.schemas import measured_time
        choices = [d for d in devices if d["device"] == "air_purifier"]
        if len(choices) != 1 or not choices[0]["online"] or not choices[0].get("updatedAt"):
            return "공기청정기의 현재 제어 원인을 확인할 수 없습니다."
        device = choices[0]
        if not 0 <= now - measured_time(device["updatedAt"]) < self.runtime.config.device_max_age:
            return "공기청정기 상태가 오래되어 현재 제어 원인을 확인할 수 없습니다."
        control = device["current_state"].get("lastControl") or {}
        if control.get("publisher") == "system":
            return "공기청정기 자체 자동 제어로 보고되었습니다. AI가 켰다고 단정하지 않습니다."
        if control.get("publisher") == "user":
            return "사용자 직접 조작으로 보고되었습니다. AI 조리 연동으로 단정하지 않습니다."
        if (record and control.get("publisher") == "api" and control.get("commandId")
                and any(a.get("deviceId") == device["deviceId"] and a.get("commandId") == control["commandId"]
                        and a.get("status") == "sent" for a in (record.get("response") or {}).get("actions", []))):
            return self.explain(record) + " 해당 명령 ID와 일치하는 기기 상태 보고도 확인했습니다."
        prefix = self.explain(record) if record else ""
        return prefix + " 현재 상태의 제어 출처는 확인되지 않아 누가 켰는지 단정할 수 없습니다."

    def eligible_feedback(self, record):
        if record is None:
            return False
        history = record["history"]
        profile = self.runtime.controller.confidence_service.config.INPUT_PROFILE
        results = (record.get("response") or {}).get("actions", [])
        return bool(record["source_id"].startswith("automation:") and history.get("action")
                    and history.get("user_id") == self.config.user_id
                    and history.get("input_profile", "legacy") == profile
                    and len(results) == len(record["payload"]["actions"]) and results
                    and all(a.get("status") == "sent" for a in results))
