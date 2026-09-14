from datetime import datetime, timedelta, timezone

from src.control import CentralController, SensingUpdate
from src.llm.factory import create_llm
from src.llm.message_generator import LLMMessageGenerator


def print_decision(title, decision):
    print()
    print("=" * 70)
    print(title)
    print("=" * 70)

    print("state :", decision.state.value)
    print("risk  :", decision.risk.value)
    print("duration :", decision.unresponsive_seconds)
    print("sensor_uncertain :", decision.sensor_uncertain)


def main():

    print("Qwen3-8B 로딩 중...")

    llm = create_llm("qwen")
    generator = LLMMessageGenerator(llm)

    controller = CentralController()

    KST = timezone(timedelta(hours=9))

    base = datetime(
        2026, 9, 15,
        10, 0, 0,
        tzinfo=KST
    ).timestamp()

    # ============================================
    # 1. 욕실 정상 진입
    # ============================================

    controller.update_sensing(
        SensingUpdate(
            location="bathroom",
            timestamp=base,
            activity="standing",
            motion_state="moving",
            fall_detected=False,
        )
    )

    # ============================================
    # 2. 낙상 감지
    # ============================================

    controller.update_sensing(
        SensingUpdate(
            location="bathroom",
            timestamp=base + 1,
            activity="lying",
            motion_state="still",
            fall_detected=True,
        )
    )

    decision = controller.bathroom_decision

    print_decision(
        "낙상 직후",
        decision,
    )

    # ============================================
    # 3. 10초 동안 움직임 없음
    # ============================================

    controller.update_sensing(
        SensingUpdate(
            location="bathroom",
            timestamp=base + 11,
            activity="lying",
            motion_state="still",
            fall_detected=False,
        )
    )

    decision = controller.bathroom_decision

    print_decision(
        "낙상 후 10초",
        decision,
    )

    # ============================================
    # 중앙 제어 결과 → RiskDecision
    # ============================================

    risk_decision = decision.to_risk_decision()

    # ============================================
    # Qwen에게 안내문 생성 요청
    # ============================================

    result = generator.generate(
        risk_decision
    )

    print()
    print("=" * 70)
    print("Qwen3-8B 출력")
    print("=" * 70)
    print(result.message)

    print()
    print("LLM:", result.llm_name)
    print("fallback:", result.fallback_used)

    if result.error:
        print("error:", result.error)


if __name__ == "__main__":
    main()