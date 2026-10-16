"""Readable end-to-end replay for confidence control, feedback, and legacy scenarios."""
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys
from uuid import uuid4

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from src.control import ApplianceUpdate, CentralController, LightContext, SensingUpdate


KST = timezone(timedelta(hours=9))


class DemoFeedbackLLM:
    """Offline stand-in; production can pass the already loaded Qwen adapter."""

    name = "manual-demo-llm"

    def generate(self, system_prompt: str, user_prompt: str) -> str:
        return json.dumps({
            "feedback": "unnecessary",
            "reason": "user_was_still_using_room",
            "confidence": 0.94,
        }, ensure_ascii=False)


def title(number: int, text: str) -> None:
    print(f"\n{'=' * 78}\n{number:02d}. {text}\n{'=' * 78}")


def show_confidence(timestamp: float, location: str, device_state: str, decision: dict) -> None:
    local_time = datetime.fromtimestamp(timestamp, KST).strftime("%H:%M:%S")
    print("시간              :", local_time)
    print("사용자 위치       :", location)
    print("센싱 confidence   :", decision["features"].get("location", "-") )
    print("현재 device 상태  :", device_state)
    print("추출된 features   :", decision["features"])
    print("현재 weights      :", decision["weights"])
    print("feature 기여도    :", decision["contributions"])
    print("최종 confidence   :", f"{decision['confidence']:.4f}")
    print("threshold         :", decision["threshold"])
    print("판단 결과         :", decision["outcome"])
    print("생성 action       :", decision["action"])


def main() -> None:
    output_dir = Path("output/manual_all_test") / f"run_{uuid4().hex[:8]}"
    controller = CentralController(
        water_dispenser_available=True,
        confidence_data_dir=output_dir,
        feedback_llm=DemoFeedbackLLM(),
    )
    base = datetime(2026, 9, 28, 7, 30, tzinfo=KST).timestamp()

    title(1, "사용자 bedroom 및 기상")
    for offset, activity in ((0, "lying"), (1, "standing"), (6, "standing")):
        controller.update_sensing(SensingUpdate("bedroom", base + offset, activity=activity))
        print(datetime.fromtimestamp(base + offset, KST).strftime("%H:%M:%S"), activity)

    title(2, "kitchen 이동")
    controller.update_sensing(SensingUpdate("living_room", base + 7, activity="walking"))
    controller.update_sensing(SensingUpdate("kitchen", base + 8, activity="standing"))
    controller.update_sensing(SensingUpdate("kitchen", base + 13, activity="standing"))
    print("현재 위치          : kitchen")

    title(3, "아침 자동 출수")
    water_commands = controller.drain_device_commands()
    print("생성 command       :", [command.to_dict() for command in water_commands])

    title(4, "전등 confidence 판단")
    light = controller.evaluate_light(LightContext(
        room="kitchen", light_on=False, user_present=True,
        timestamp=base + 14, presence_duration=5,
        location_confidence=0.96, activity_confidence=0.9, sensor_consistency=0.95,
    ))
    show_confidence(base + 14, "kitchen", "light OFF", light.to_dict())
    controller.drain_automation_actions()

    title(5, "조리 시작")
    controller.update_appliance(ApplianceUpdate(True, base + 15, power_watts=1800))
    controller.update_sensing(SensingUpdate(
        "kitchen", base + 15, activity="cooking", confidence=0.96,
        activity_confidence=0.95,
    ))
    print("현재 device 상태  : stove ON / 1800 W")

    title(6, "주방 이탈")
    first_away = None
    reduce_action = None
    for offset in range(20, 321, 5):
        timestamp = base + offset
        appliance_decision = controller.update_appliance(
            ApplianceUpdate(True, timestamp, power_watts=1800)
        )
        sensing_decision = controller.update_sensing(SensingUpdate(
            "living_room", timestamp, activity="walking", confidence=0.96,
            activity_confidence=0.95,
        ))
        scored = sensing_decision.confidence_decision or appliance_decision.confidence_decision
        if first_away is None and scored is not None:
            first_away = scored
        actions = controller.drain_automation_actions()
        if actions:
            reduce_action = actions[0]
            break
    title(7, "confidence 점수 변화")
    show_confidence(base + 25, "living_room", "stove ON / 1800 W", first_away)
    title(8, "threshold 초과")
    final_decision = controller.decision_history.get(reduce_action.action_id)
    show_confidence(reduce_action.timestamp, "living_room", "stove ON / 1800 W", final_decision)

    title(9, "화력 감소")
    print("생성 action       :", reduce_action.to_dict())

    title(10, "사용자 '불필요했다' feedback")
    before_score = final_decision["confidence"]
    feedback = controller.apply_feedback(reduce_action.action_id, "unnecessary")
    print("feedback           :", feedback["feedback"])

    title(11, "scenario weight 변경")
    print("적용 전 weight     :", feedback["weights_before"])
    print("적용 후 weight     :", feedback["weights_after"])

    title(12, "동일 조건 재실행")
    features = dict(final_decision["features"])
    features["feedback"] = controller.feedback_manager.feedback_score(
        controller.user_id, "kitchen_leave_reduce_power"
    )
    rescored = controller.confidence_engine.calculate(
        "kitchen_leave_reduce_power", features, controller.user_id
    )
    print("재계산 features    :", features)
    print("재계산 confidence  :", f"{rescored['confidence']:.4f}")

    title(13, "이전 confidence와 비교")
    print("feedback 전 score  :", f"{before_score:.4f}")
    print("feedback 후 score  :", f"{rescored['confidence']:.4f}")
    print("score 감소 확인    :", rescored["confidence"] < before_score)

    title(14, "주방 복귀")
    return_start = reduce_action.timestamp + 5
    controller.update_appliance(ApplianceUpdate(True, return_start, power_watts=900))
    early = controller.update_sensing(SensingUpdate("kitchen", return_start, confidence=0.97))
    if early.confidence_decision:
        show_confidence(return_start, "kitchen", "HOMEVIS_REDUCED", early.confidence_decision)
    title(15, "restore_power 판단")
    stable_time = return_start + 5
    controller.update_appliance(ApplianceUpdate(True, stable_time, power_watts=900))
    restored = controller.update_sensing(SensingUpdate("kitchen", stable_time, confidence=0.97))
    show_confidence(stable_time, "kitchen", "HOMEVIS_REDUCED", restored.confidence_decision)

    title(16, "욕실 낙상 시나리오")
    fall_time = stable_time + 10
    controller.update_sensing(SensingUpdate(
        "bathroom", fall_time, activity="lying", motion_state="still", fall_detected=True
    ))
    fall = controller.update_sensing(SensingUpdate(
        "bathroom", fall_time + 10, activity="lying", motion_state="still", fall_detected=False
    ))
    print("욕실 판단 state    :", controller.bathroom_decision.state.value)
    print("욕실 판단 risk     :", controller.bathroom_decision.risk.value)
    print("주방 realtime state:", fall.state.value)

    print(f"\n{'=' * 78}\n[자동화 발생]\n{'=' * 78}")
    light_off = controller.evaluate_light(LightContext(
        room="living_room", light_on=True, user_present=False,
        timestamp=fall_time + 20, absence_duration=30,
        location_confidence=0.98, activity_confidence=0.95, sensor_consistency=0.97,
    ))
    print("Action ID          :", light_off.action_id)
    print("Scenario           :", light_off.scenario)
    print("Action             :", light_off.action.action)
    print("Action Confidence  :", f"{light_off.confidence:.4f}")
    print("Features           :", light_off.features)
    print("Weights            :", light_off.weights)

    raw_feedback = "나 아직 거실에 있는데 왜 불 껐어?"
    print(f"\n{'=' * 78}\n[사용자 자연어 피드백]\n{'=' * 78}")
    print(raw_feedback)
    interpreted = controller.apply_natural_language_feedback(
        light_off.action_id, raw_feedback
    )
    parsed = interpreted["parsed_feedback"]

    print(f"\n{'=' * 78}\n[LLM Feedback Interpretation]\n{'=' * 78}")
    print("Feedback           :", parsed["feedback"])
    print("Reason             :", parsed["reason"])
    print("Feedback Confidence:", parsed["confidence"])

    print(f"\n{'=' * 78}\n[기존 FeedbackManager 호출]\n{'=' * 78}")
    print("Scenario           :", interpreted["scenario"])
    print("Weight Updated     :", interpreted["weight_updated"])
    print("Before             :", interpreted.get("weights_before"))
    print("After              :", interpreted.get("weights_after"))

    repeated_light = controller.evaluate_light(LightContext(
        room="living_room", light_on=True, user_present=False,
        timestamp=fall_time + 21, absence_duration=30,
        location_confidence=0.98, activity_confidence=0.95, sensor_consistency=0.97,
    ))
    print(f"\n{'=' * 78}\n[동일 상황 재판단]\n{'=' * 78}")
    print("Previous Confidence:", f"{light_off.confidence:.4f}")
    print("Updated Confidence :", f"{repeated_light.confidence:.4f}")

    print("\n저장 위치:", output_dir.resolve())


if __name__ == "__main__":
    main()
