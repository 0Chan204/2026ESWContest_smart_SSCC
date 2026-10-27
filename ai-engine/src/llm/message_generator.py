from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from src.llm.adapters.base import BaseLLMAdapter
from src.llm.prompts import build_device_command_user_prompt, build_user_prompt, get_system_prompt
from src.models import RiskDecision, RiskLevel

if TYPE_CHECKING:
    from src.control.scenario_models import DeviceCommand


DEFAULT_MESSAGES: dict[str, str] = {
    "WARNING": "조리 상태를 확인해 주세요.",
    "HIGH": "조리 중 위험 상황이 감지되었습니다. 즉시 주방 상태를 확인해 주세요.",
    "COOKING_UNATTENDED_WARNING": (
        "조리 중 자리를 비우셨습니다. 주방 상태를 확인해 주세요."
    ),
    "COOKING_UNATTENDED_HIGH": (
        "조리 중 자리를 비우신 상태에서 위험 상황이 감지되었습니다. "
        "즉시 주방 상태를 확인해 주세요."
    ),
}


@dataclass(frozen=True)
class MessageGenerationResult:
    message: str
    llm_name: str
    prompt_version: str
    fallback_used: bool
    error: str | None = None


def get_default_message(decision: RiskDecision) -> str:
    if decision.risk_level is RiskLevel.NORMAL:
        return ""

    situation = (decision.situation or "").upper()
    if (decision.decision_context or {}).get("scenario") == "bathroom_fall":
        if situation == "FALL_EMERGENCY":
            return "욕실에서 낙상 후 움직임이 확인되지 않고 있습니다."
        return "욕실에서 낙상 가능성이 감지되었습니다. 괜찮으신가요?"
    user_state = (decision.user_state or "").upper()

    unattended = situation == "COOKING_UNATTENDED" or user_state == "OUT"
    if unattended:
        key = f"COOKING_UNATTENDED_{decision.risk_level.value}"
        if key in DEFAULT_MESSAGES:
            return DEFAULT_MESSAGES[key]

    return DEFAULT_MESSAGES[decision.risk_level.value]


def get_default_device_command_message(command: "DeviceCommand") -> str:
    return f"물 {command.amount_ml}밀리리터를 준비하도록 요청했습니다."


def claims_dispense_completion(message: str) -> bool:
    return any(phrase in message for phrase in (
        "준비되었습니다",
        "준비됐습니다",
        "준비했습니다",
        "준비가 완료",
        "출수가 완료",
        "출수 완료",
        "출수되었습니다",
        "출수됐습니다",
        "나왔습니다",
        "나왔어요",
    ))


class LLMMessageGenerator:
    """Generate a spoken message with LLM -> fallback behavior."""

    def __init__(
        self,
        llm: BaseLLMAdapter | None = None,
        prompt_version: str = "v1",
    ) -> None:
        self.llm = llm
        self.prompt_version = prompt_version

    @property
    def llm_name(self) -> str:
        return self.llm.name if self.llm is not None else "none"

    def generate(self, decision: RiskDecision) -> MessageGenerationResult:
        fallback = get_default_message(decision)

        if decision.risk_level is RiskLevel.NORMAL:
            return MessageGenerationResult(
                message="",
                llm_name=self.llm_name,
                prompt_version=self.prompt_version,
                fallback_used=False,
            )

        if self.llm is None:
            return MessageGenerationResult(
                message=fallback,
                llm_name="none",
                prompt_version=self.prompt_version,
                fallback_used=True,
            )

        try:
            response = self.llm.generate(
                get_system_prompt(self.prompt_version, (decision.decision_context or {}).get("scenario")),
                build_user_prompt(decision),
            )
            cleaned = response.strip()
            if not cleaned:
                raise ValueError("LLM returned an empty response")

            return MessageGenerationResult(
                message=cleaned,
                llm_name=self.llm_name,
                prompt_version=self.prompt_version,
                fallback_used=False,
            )
        except Exception as exc:
            return MessageGenerationResult(
                message=fallback,
                llm_name=self.llm_name,
                prompt_version=self.prompt_version,
                fallback_used=True,
                error=type(exc).__name__,
            )

    def generate_device_command(self, command: "DeviceCommand") -> MessageGenerationResult:
        """Describe an issued morning-water command without claiming completion."""
        fallback = get_default_device_command_message(command)

        if self.llm is None:
            return MessageGenerationResult(
                message=fallback,
                llm_name="none",
                prompt_version=self.prompt_version,
                fallback_used=True,
            )

        try:
            response = self.llm.generate(
                get_system_prompt(self.prompt_version, "morning_water"),
                build_device_command_user_prompt(command),
            )
            cleaned = response.strip()
            if not cleaned:
                raise ValueError("LLM returned an empty response")
            if claims_dispense_completion(cleaned):
                raise ValueError("LLM claimed unconfirmed water dispensing completion")

            return MessageGenerationResult(
                message=cleaned,
                llm_name=self.llm_name,
                prompt_version=self.prompt_version,
                fallback_used=False,
            )
        except Exception as exc:
            return MessageGenerationResult(
                message=fallback,
                llm_name=self.llm_name,
                prompt_version=self.prompt_version,
                fallback_used=True,
                error=type(exc).__name__,
            )
