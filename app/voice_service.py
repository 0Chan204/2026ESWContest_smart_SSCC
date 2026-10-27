"""
음성 명령을 처리하는 서비스입니다. (v0.6, docs/VOICE.md)

흐름:
1) 대시보드가 인식한 전체 문장을 POST /voice/commands로 보냄 -> create_command()
   저장하고 AI 판정 엔진에 MQTT(VOICE_REQUEST_TOPIC)로 전달, 상태 thinking
2) 판정 엔진이 POST /ai/decisions에 voiceId를 담아 판단을 보냄 -> app/ai_service.py가 claim_for_decision()으로 연결
   - 제어 없이 답변만: answered
   - 제어가 있고 확인이 필요 없음: 바로 실행 후 executed
   - 제어가 있고 requiresConfirmation=true: 실행을 보류하고 confirm_required (확인 문구는 서버가 만듦)
3) 대시보드가 확인 창 결과를 POST /voice/commands/{id}/confirm으로 보냄 -> confirm()
   승인하면 보류한 제어를 실행(executed), 거절하면 cancelled
4) 시간 초과: VOICE_AI_TIMEOUT_SEC 안에 판단이 없으면 timeout,
   VOICE_CONFIRM_TIMEOUT_SEC 안에 확인이 없으면 cancelled

(v0.9) 보드 마이크 음성 명령은 app/voice_listen_service.py가 녹음·음성 인식을 한 뒤
submit_recognized()로 같은 흐름(2~4)에 넣습니다. listening -> recognizing -> received -> thinking ...

상태가 바뀔 때마다 WebSocket voice.status로 대시보드에 알리고,
확인 문구·답변은 보드 스피커로 읽어 줍니다(app/voice_speaker.py, 설정 speak).
판정 엔진 응답·사용자 확인·시간 초과가 동시에 일어나도 state_store.transition_voice_command()가
한 가지만 반영합니다.
"""

import asyncio
import logging
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from app import device_registry, state_store, voice_speaker, ws_hub
from app.config import settings
from app.schemas import AiAction, AiActionResult, VoiceCommand, VoiceCommandIn

logger = logging.getLogger("induction.voice")

WAITING_AI = {"received", "thinking"}
WAITING_CONFIRM = {"confirm_required"}

_ROOM_LABEL = {"room": "방", "kitchen": "주방", "toilet": "욕실"}
_DEVICE_LABEL = {
    "light": "조명", "fan": "환풍기", "water_purifier": "정수기", "stove": "인덕션", "air_purifier": "공기청정기",
}
_MODE_LABEL = {"auto": "자동", "manual": "수동"}
_SPEED_LABEL = {"low": "약", "mid": "중", "high": "강"}

# 시작어 "홈비스" (v0.7). 음성 인식이 "홈 비스", "홈비즈", "홈비쓰", "홈비스야", "HomeVIS"처럼 적어도 시작어로 봅니다.
_WAKE_WORD = re.compile(r"^\s*(?:홈\s*비\s*[스즈쓰]|home\s*vis)(?:야|아)?[\s,.!?~·]*", re.IGNORECASE)


class UnknownVoiceCommand(Exception):
    pass


class VoiceCommandError(Exception):
    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code
        self.message = message


class VoicePublishFailed(Exception):
    pass


class EmptyVoiceCommand(Exception):
    """시작어만 있고 명령 문장이 없음"""


def strip_wake_word(text: str) -> tuple[str, bool]:
    """문장 앞의 시작어를 떼어 냅니다. (남은 문장, 시작어가 있었는지)"""
    match = _WAKE_WORD.match(text)
    if match is None:
        return text.strip(), False
    return text[match.end():].strip(), True


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.isoformat(timespec="milliseconds")


def new_voice_id() -> str:
    return f"voice-{_now().strftime('%Y%m%d')}-{uuid.uuid4().hex[:8]}"



def broadcast(command: VoiceCommand) -> None:
    """대시보드에 voice.status로 알리고, 확인 문구·답변은 보드 스피커로 읽어 줍니다."""
    ws_hub.broadcast_threadsafe("voice.status", command.model_dump(exclude={"pendingActions"}))
    voice_speaker.on_voice_status(command)



def fail(voice_id: str, reason: str, expected: set[str]) -> Optional[VoiceCommand]:
    """아직 expected 상태면 failed(+이유)로 바꾸고 알립니다."""
    failed = state_store.transition_voice_command(
        voice_id, expected, status="failed", reason=reason, updatedAt=_iso(_now())
    )
    if failed is not None:
        broadcast(failed)
    return failed


def _seconds_until(iso_time: Optional[str]) -> float:
    if not iso_time:
        return 0.0
    return max((datetime.fromisoformat(iso_time) - _now()).total_seconds(), 0.0)


# ---------------------------------------------------------------------------
# 1) 문장 받기 -> 판정 엔진에 전달
# ---------------------------------------------------------------------------

def request_message(command: VoiceCommand) -> dict:
    """판정 엔진에 보내는 MQTT 메시지"""
    return {
        "voiceId": command.voiceId,
        "text": command.text,
        "rawText": command.rawText,
        "wakeWord": command.wakeWord,
        "lang": command.lang,
        "confidence": command.confidence,
        "source": command.source,
        "recognizedAt": command.recognizedAt,
        "receivedAt": command.receivedAt,
        "expiresAt": command.expiresAt,
    }


def create_command(request: VoiceCommandIn) -> VoiceCommand:
    """문장을 저장하고 판정 엔진에 MQTT로 보냅니다. 보내지 못하면 failed로 남기고 VoicePublishFailed.
    문장 앞의 시작어("홈비스")는 떼어 내고 wakeWord=true로 표시합니다. 시작어만 있으면 EmptyVoiceCommand"""
    text, wake_word = strip_wake_word(request.text)
    if not text:
        raise EmptyVoiceCommand(request.text)
    now = _now()
    command = VoiceCommand(
        voiceId=new_voice_id(),
        text=text,
        rawText=request.text,
        wakeWord=wake_word,
        lang=request.lang,
        confidence=request.confidence,
        source=request.source,
        recognizedAt=request.recognizedAt,
        receivedAt=_iso(now),
        status="received",
        expiresAt=_iso(now + timedelta(seconds=settings.VOICE_AI_TIMEOUT_SEC)),
        updatedAt=_iso(now),
    )
    state_store.save_voice_command(command)
    return _dispatch(command)


def submit_recognized(voice_id: str, raw_text: str, confidence: Optional[float]) -> Optional[VoiceCommand]:
    """(v0.9) 보드 마이크로 인식한 문장을 기존 음성 명령 흐름에 넣습니다.
    인식 중(recognizing)이 아니면(취소됨 등) 아무것도 하지 않고 None. 시작어만 있으면 failed(no_speech)."""
    text, wake_word = strip_wake_word(raw_text)
    if not text:
        return fail(voice_id, "no_speech", {"recognizing"})
    now = _now()
    command = state_store.transition_voice_command(
        voice_id, {"recognizing"},
        text=text, rawText=raw_text, wakeWord=wake_word, confidence=confidence, recognizedAt=_iso(now),
        status="received", expiresAt=_iso(now + timedelta(seconds=settings.VOICE_AI_TIMEOUT_SEC)), updatedAt=_iso(now),
    )
    if command is None:
        return None
    try:
        return _dispatch(command)
    except VoicePublishFailed:
        return state_store.get_voice_command(voice_id)


def _dispatch(command: VoiceCommand) -> VoiceCommand:
    """저장된 음성 명령(received)을 판정 엔진에 MQTT로 보내고 thinking으로 바꿉니다."""
    from app import mqtt_client  # 지연 import: 순환 참조 방지

    try:
        info = mqtt_client.publish_json(settings.VOICE_REQUEST_TOPIC, request_message(command), qos=1)
        if info is not None and getattr(info, "rc", 0) != 0:
            raise RuntimeError(f"rc={info.rc}")
    except Exception as exc:
        logger.error("음성 명령을 판정 엔진에 보내지 못했습니다 (voiceId=%s): %s", command.voiceId, exc)
        fail(command.voiceId, "publish_failed", WAITING_AI)
        raise VoicePublishFailed(command.voiceId) from exc

    thinking = state_store.transition_voice_command(
        command.voiceId, {"received"}, status="thinking", updatedAt=_iso(_now())
    )
    if thinking is not None:
        broadcast(thinking)
        command = thinking
    logger.info("음성 명령 전달 (voiceId=%s): %s", command.voiceId, command.text)
    ws_hub.run_coroutine_threadsafe(_ai_timeout_watchdog(command.voiceId))
    return command


# ---------------------------------------------------------------------------
# 2) 판정 엔진의 판단 연결 (app/ai_service.py에서 호출)
# ---------------------------------------------------------------------------

def _particle(word: str, with_batchim: str, without: str) -> str:
    last = word[-1] if word else ""
    if "가" <= last <= "힣":
        return with_batchim if (ord(last) - ord("가")) % 28 else without
    return f"{with_batchim}({without})"


def _target_label(action: AiAction, room: Optional[str]) -> str:
    device = None
    if action.deviceId:
        device = device_registry.get_device(action.deviceId)
    if device is None:
        device = device_registry.find_device(action.device, room)
    device_room = device.room if device is not None else room
    name = _DEVICE_LABEL.get(action.device, action.device)
    room_label = _ROOM_LABEL.get(device_room or "", "")
    return f"{room_label} {name}".strip()


def _action_phrase(action: AiAction) -> tuple[str, str]:
    """(확인 질문용 동사구, 여러 개를 묶을 때 쓰는 명사구)"""
    a = action.action
    if a == "turn_on" and action.level:
        return f"{action.level}단으로 켤까요", f"{action.level}단으로 켜기"
    if a in ("on", "turn_on"):
        return "켤까요", "켜기"
    if a in ("off", "turn_off"):
        return "끌까요", "끄기"
    if a == "blink":
        return "깜빡일까요", "깜빡이기"
    if a == "fadeout":
        return "어둡게 할까요", "어둡게 하기"
    if a == "set_speed":
        speed = _SPEED_LABEL.get(action.speed or "", action.speed or "")
        return f"풍량을 {speed}{_particle(speed, '으로', '로')} 바꿀까요", f"풍량 {speed}"
    if a == "set_mode":
        mode = _MODE_LABEL.get(action.mode or "", action.mode or "")
        return f"{mode} 모드로 바꿀까요", f"{mode} 모드"
    if a == "set_level":
        return f"화력 {action.level}단으로 바꿀까요", f"화력 {action.level}단"
    if a == "restore_power":
        return "이전 화력으로 켤까요", "이전 화력으로 켜기"
    if a == "dispense":
        return f"물 {action.amountMl}ml 받을까요", f"물 {action.amountMl}ml"
    return f"{a} 할까요", a


def build_confirm_text(actions: list[AiAction], room: Optional[str]) -> str:
    """확인 창 문구. 예) "욕실 조명을 켤까요?", "욕실 조명 켜기, 주방 환풍기 끄기를 실행할까요?" """
    if len(actions) == 1:
        action = actions[0]
        target = _target_label(action, room)
        verb, _ = _action_phrase(action)
        if action.action in ("set_speed", "set_level"):
            return f"{target} {verb}?"
        if action.action == "set_mode":
            return f"{target}{_particle(target, '을', '를')} {verb}?"
        if action.action == "dispense":
            return f"{target}에서 {verb}?"
        return f"{target}{_particle(target, '을', '를')} {verb}?"
    parts = [f"{_target_label(a, room)} {_action_phrase(a)[1]}" for a in actions]
    joined = ", ".join(parts)
    return f"{joined}{_particle(joined, '을', '를')} 실행할까요?"


def claim_for_decision(
    voice_id: str, decision_id: str, answer: Optional[str], actions: list[AiAction],
    requires_confirmation: bool, room: Optional[str],
) -> Optional[VoiceCommand]:
    """판정 엔진의 판단을 이 음성 명령에 연결합니다.
    아직 판단을 기다리는 중이면 다음 상태로 바꾼 기록을, 이미 끝났으면(timeout·다른 판단) None을 돌려줍니다.
    없는 voiceId면 UnknownVoiceCommand"""
    if state_store.get_voice_command(voice_id) is None:
        raise UnknownVoiceCommand(voice_id)

    now = _now()
    changes = {"decisionId": decision_id, "answer": answer, "updatedAt": _iso(now)}
    if actions and requires_confirmation:
        changes.update(
            status="confirm_required",
            requiresConfirmation=True,
            confirmText=build_confirm_text(actions, room),
            confirmDeadline=_iso(now + timedelta(seconds=settings.VOICE_CONFIRM_TIMEOUT_SEC)),
            pendingActions=list(actions),
        )
    else:
        # 실행 결과는 finish()에서 채웁니다. 여기서 먼저 상태를 바꿔 timeout과 겹치지 않게 합니다.
        changes.update(status="executed" if actions else "answered")
    claimed = state_store.transition_voice_command(voice_id, WAITING_AI, **changes)
    if claimed is not None and claimed.status == "confirm_required":
        broadcast(claimed)
        ws_hub.run_coroutine_threadsafe(_confirm_timeout_watchdog(voice_id))
    return claimed


def finish(voice_id: str, results: list[AiActionResult]) -> Optional[VoiceCommand]:
    """제어 실행이 끝난 음성 명령에 결과를 채우고 대시보드에 알립니다."""
    command = state_store.transition_voice_command(
        voice_id, {"executed", "answered"}, actions=results, updatedAt=_iso(_now())
    )
    if command is not None:
        broadcast(command)
    return command


# ---------------------------------------------------------------------------
# 3) 사용자 확인
# ---------------------------------------------------------------------------

def confirm(voice_id: str, approved: bool) -> VoiceCommand:
    command = state_store.get_voice_command(voice_id)
    if command is None:
        raise UnknownVoiceCommand(voice_id)

    now = _iso(_now())
    if not approved:
        cancelled = state_store.transition_voice_command(
            voice_id, WAITING_CONFIRM, status="cancelled", confirmedAt=now, pendingActions=[], updatedAt=now
        )
        if cancelled is None:
            raise VoiceCommandError(409, f"확인을 기다리는 명령이 아닙니다 (현재 상태: {command.status}).")
        _close_decision(cancelled, "cancelled")
        broadcast(cancelled)
        return cancelled

    approved_command = state_store.transition_voice_command(
        voice_id, WAITING_CONFIRM, status="executed", confirmedAt=now, updatedAt=now
    )
    if approved_command is None:
        raise VoiceCommandError(409, f"확인을 기다리는 명령이 아닙니다 (현재 상태: {command.status}).")

    from app import ai_service  # 지연 import: 순환 참조 방지

    results = ai_service.execute_confirmed(approved_command)
    finished = state_store.transition_voice_command(
        voice_id, {"executed"}, actions=results, pendingActions=[], updatedAt=_iso(_now())
    )
    command = finished or approved_command
    broadcast(command)
    return command


def _close_decision(command: VoiceCommand, reason: str) -> None:
    """확인 대기 중이던 판단 기록을 취소로 바꿉니다."""
    if not command.decisionId:
        return
    record = state_store.get_ai_decision(command.decisionId)
    if record is None:
        return
    actions = [r.model_copy(update={"status": "cancelled", "message": reason}) for r in record.actions]
    state_store.update_ai_decision(command.decisionId, status="cancelled", actions=actions)


# ---------------------------------------------------------------------------
# 4) 시간 초과
# ---------------------------------------------------------------------------

def expire_if_waiting(voice_id: str) -> Optional[VoiceCommand]:
    """판정 엔진의 판단을 아직 못 받았으면 timeout으로 바꿉니다."""
    expired = state_store.transition_voice_command(voice_id, WAITING_AI, status="timeout", updatedAt=_iso(_now()))
    if expired is not None:
        logger.warning("판정 엔진 응답이 없어 음성 명령을 timeout 처리합니다 (voiceId=%s)", voice_id)
        broadcast(expired)
    return expired


def cancel_if_unconfirmed(voice_id: str) -> Optional[VoiceCommand]:
    """확인 시간이 지났는데도 답이 없으면 취소합니다."""
    now = _iso(_now())
    cancelled = state_store.transition_voice_command(
        voice_id, WAITING_CONFIRM, status="cancelled", pendingActions=[], updatedAt=now
    )
    if cancelled is not None:
        logger.info("확인 시간이 지나 음성 명령을 취소합니다 (voiceId=%s)", voice_id)
        _close_decision(cancelled, "확인 시간 초과")
        broadcast(cancelled)
    return cancelled


async def _ai_timeout_watchdog(voice_id: str) -> None:
    command = state_store.get_voice_command(voice_id)
    if command is None:
        return
    await asyncio.sleep(_seconds_until(command.expiresAt))
    await asyncio.to_thread(expire_if_waiting, voice_id)


async def _confirm_timeout_watchdog(voice_id: str) -> None:
    command = state_store.get_voice_command(voice_id)
    if command is None:
        return
    await asyncio.sleep(_seconds_until(command.confirmDeadline))
    await asyncio.to_thread(cancel_if_unconfirmed, voice_id)


def resume_pending() -> int:
    """서버 시작 시: 판단·확인을 기다리던 음성 명령의 시간 초과 타이머를 다시 겁니다.
    이미 기한이 지났으면 곧바로 timeout·취소됩니다."""
    count = 0
    for command in state_store.list_voice_commands():
        if command.status in ("listening", "recognizing"):
            # (v0.9) 녹음·인식 중에 서버가 꺼졌던 명령은 이어서 할 수 없으니 실패로 끝냅니다.
            fail(command.voiceId, "interrupted", {"listening", "recognizing"})
        elif command.status in WAITING_AI:
            ws_hub.run_coroutine_threadsafe(_ai_timeout_watchdog(command.voiceId))
            count += 1
        elif command.status in WAITING_CONFIRM:
            ws_hub.run_coroutine_threadsafe(_confirm_timeout_watchdog(command.voiceId))
            count += 1
    if count:
        logger.info("기다리던 음성 명령 %d건의 시간 초과 타이머를 다시 걸었습니다.", count)
    return count
