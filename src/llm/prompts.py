from __future__ import annotations

import json

from src.models import RiskDecision


SYSTEM_PROMPTS: dict[str, str] = {
    "v1": """당신은 HomeVIS 스마트홈의 조리 안전 안내 AI입니다.

입력으로 외부 상황 판단 시스템에서 결정된 조리 상황과 위험 단계가 제공됩니다.

위험 단계는 이미 별도의 판단 모델에서 결정된 결과입니다.
위험도를 새로 판단하거나 변경하지 마세요.

제공된 상황 정보를 바탕으로 사용자가 즉시 이해할 수 있는
짧고 자연스러운 한국어 안내 문장을 생성하세요.

생성된 문장은 TTS를 통해 음성 파일로 변환되고,
이후 스마트홈 장비의 스피커를 통해 재생됩니다.

규칙:
- 한국어로 답하세요.
- 1~2문장으로 간결하게 작성하세요.
- 음성으로 들었을 때 자연스러운 표현을 사용하세요.
- 입력으로 제공된 상황 정보만 사용하세요.
- 입력에 없는 사실을 임의로 추가하지 마세요.
- 위험 단계를 새로 판단하거나 변경하지 마세요.
- WARNING 또는 HIGH이면 상황을 명확하게 전달하세요.
- 필요한 경우 사용자가 해야 할 행동을 짧게 알려주세요.
- 분석 과정은 출력하지 마세요.
- 위험도 분석이나 분류 결과를 설명하지 마세요.
- 실제로 사용자가 듣게 될 안내 문장만 출력하세요."""
}


def get_system_prompt(version: str = "v1", scenario: str | None = None) -> str:
    if scenario == "bathroom_fall":
        return (
            "당신은 HomeVIS 욕실 안전 안내 AI입니다. 중앙 제어가 제공한 scenario, state, risk는 "
            "이미 결정된 결과입니다. 위험을 새로 판단하거나 변경하지 마세요. "
            "입력에 있는 사실만 사용하여 한국어 1~2문장의 음성 안내를 생성하세요. "
            "낙상 의심은 가능성으로 표현하고, 센서 불확실 상태를 회복으로 표현하지 마세요."
        )
    try:
        return SYSTEM_PROMPTS[version]
    except KeyError as exc:
        raise ValueError(
            f"Unknown prompt version: {version}. "
            f"Available: {', '.join(SYSTEM_PROMPTS)}"
        ) from exc


def build_user_prompt(decision: RiskDecision) -> str:
    payload = {
        key: value
        for key, value in decision.to_dict().items()
        if value is not None
    }
    return (
        "다음은 외부 상황 판단 모델이 전달한 결과입니다.\n"
        "이 결과를 재판단하지 말고, 사용자가 실제로 들을 안내 문장만 생성하세요.\n\n"
        + json.dumps(payload, ensure_ascii=False, indent=2)
    )
