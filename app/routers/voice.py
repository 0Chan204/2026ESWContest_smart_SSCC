"""
음성 명령 REST API입니다. (v0.6, Swagger 섹션: 음성 명령, docs/VOICE.md)

- POST /voice/commands                  대시보드가 인식한 전체 문장 전송 -> 저장 + AI 판정 엔진에 MQTT 전달
- GET  /voice/commands                  음성 명령 기록 (최신순, status로 거르기)
- GET  /voice/commands/{voiceId}        1건 조회
- POST /voice/commands/{voiceId}/confirm  확인 창 결과 (실행 / 취소)
- (v0.9) POST /voice/listen             보드 마이크로 듣기 시작 (녹음 + 음성 인식은 서버가 함)
- (v0.9) POST /voice/listen/cancel      듣기 취소
- (v0.9) GET/PUT /voice/settings        호출어 · 음성 안내(speak) 설정

진행 상황은 WebSocket /api/v1/stream 의 voice.status 이벤트로 알립니다.
"""

from typing import Optional

from fastapi import APIRouter, HTTPException, Query, status

from app import state_store, voice_listen_service, voice_service, ws_hub
from app.schemas import (
    VoiceCommand,
    VoiceCommandAccepted,
    VoiceCommandIn,
    VoiceCommandListResponse,
    VoiceConfirmRequest,
    VoiceListenAccepted,
    VoiceListenCancelRequest,
    VoiceSettings,
    VoiceSettingsUpdate,
    VoiceStatus,
)

TAG = "음성 명령"
router = APIRouter(prefix="/voice")


@router.post("/commands", response_model=VoiceCommandAccepted, status_code=status.HTTP_202_ACCEPTED, tags=[TAG], summary="음성 명령 문장 전송 (대시보드 → 서버)")
def receive_voice_command(request: VoiceCommandIn) -> VoiceCommandAccepted:
    """
    인식이 끝난 **전체 문장**을 보냅니다. 서버는 저장하고 AI 판정 엔진에 MQTT(home/voice/request)로 전달합니다.

    - 응답의 voiceId로 이후 WebSocket voice.status 이벤트를 구분합니다.
      thinking -> (confirm_required) -> executed / answered / cancelled / timeout / failed
    - 판정 엔진에 전달하지 못하면(브로커 연결 끊김 등) 503입니다. 대시보드는 "지금은 음성 명령을 쓸 수 없어요"를 표시합니다.
    - 화면 이동 명령("주방", "설정" 등)은 대시보드에서 처리하고 보내지 않습니다.
    - (v0.7) 문장 앞의 시작어("홈비스", "홈 비스", "홈비즈" 등)는 서버가 떼어 내고 wakeWord=true로 판정 엔진에 전달합니다.
      시작어만 있고 뒤 문장이 없으면 422입니다.
    """
    try:
        command = voice_service.create_command(request)
    except voice_service.EmptyVoiceCommand as exc:
        raise HTTPException(status_code=422, detail="시작어 뒤에 명령 문장이 없습니다.") from exc
    except voice_service.VoicePublishFailed as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "VOICE_UNAVAILABLE", "voiceId": str(exc), "message": "AI 판정 엔진에 전달하지 못했습니다."},
        ) from exc
    return VoiceCommandAccepted(voiceId=command.voiceId, receivedAt=command.receivedAt)


@router.get("/commands", response_model=VoiceCommandListResponse, tags=[TAG], summary="음성 명령 기록 조회")
def list_voice_commands(
    status_: Optional[VoiceStatus] = Query(default=None, alias="status"), limit: int = 50
) -> VoiceCommandListResponse:
    """최신순. status를 주면 그 상태만 돌려줍니다 (예: AI 판정 엔진이 놓친 명령 확인 status=thinking)."""
    wanted = status_
    items = [c for c in state_store.list_voice_commands() if wanted is None or c.status == wanted]
    newest_first = list(reversed(items))
    return VoiceCommandListResponse(items=newest_first[: max(limit, 0)], total=len(items))


@router.get("/commands/{voice_id}", response_model=VoiceCommand, tags=[TAG], summary="음성 명령 1건 조회")
def read_voice_command(voice_id: str) -> VoiceCommand:
    command = state_store.get_voice_command(voice_id)
    if command is None:
        raise HTTPException(status_code=404, detail="해당 voiceId를 찾을 수 없습니다.")
    return command


@router.post("/commands/{voice_id}/confirm", response_model=VoiceCommand, tags=[TAG], summary="확인 창 결과 전송 (실행 / 취소)")
def confirm_voice_command(voice_id: str, request: VoiceConfirmRequest) -> VoiceCommand:
    """
    confirm_required 상태의 명령에만 보낼 수 있습니다. approved=true면 보류한 제어를 실행하고(executed),
    false면 취소합니다(cancelled). 확인 시간(VOICE_CONFIRM_TIMEOUT_SEC, 기본 30초)이 지나면 서버가 자동 취소합니다.
    이미 끝난 명령이면 409입니다.
    """
    try:
        return voice_service.confirm(voice_id, request.approved)
    except voice_service.UnknownVoiceCommand as exc:
        raise HTTPException(status_code=404, detail="해당 voiceId를 찾을 수 없습니다.") from exc
    except voice_service.VoiceCommandError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


# ---------------------------------------------------------------------------
# v0.9: 보드 마이크 (docs/VOICE.md 5장)
# ---------------------------------------------------------------------------

@router.post("/listen", response_model=VoiceListenAccepted, status_code=status.HTTP_202_ACCEPTED, tags=[TAG], summary="보드 마이크로 듣기 시작 (마이크 버튼)")
def start_listening() -> VoiceListenAccepted:
    """
    보드에 연결된 마이크로 녹음하고, 서버가 음성 인식(STT)까지 한 뒤 기존 음성 명령 흐름으로 넘깁니다.

    - 진행 상황은 WebSocket voice.status: listening(듣는 중) -> recognizing(알아듣는 중, 인식되면 text 포함)
      -> received -> thinking -> (confirm_required) -> executed / answered ...
    - 실패하면 failed + reason: mic_unavailable(마이크 없음) · no_speech(말소리 없음) · stt_error(인식 실패, 인터넷 등)
    - 한 번에 하나만 듣습니다. 이미 듣는 중이면 409이고 detail.voiceId로 그 명령을 알려줍니다.
    - 서버에서 마이크를 끈 경우(VOICE_LISTEN_ENABLED=false) 503입니다.
    """
    try:
        command = voice_listen_service.start_listen(source="button")
    except voice_listen_service.AlreadyListening as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "ALREADY_LISTENING", "voiceId": exc.voice_id, "message": "이미 듣는 중입니다."},
        ) from exc
    except voice_listen_service.ListenDisabled as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "LISTEN_DISABLED", "message": "이 서버에서는 보드 마이크를 사용하지 않습니다."},
        ) from exc
    return VoiceListenAccepted(voiceId=command.voiceId, receivedAt=command.receivedAt)


@router.post("/listen/cancel", response_model=VoiceCommand, tags=[TAG], summary="듣기 취소")
def cancel_listening(request: VoiceListenCancelRequest) -> VoiceCommand:
    """듣는 중(listening) · 알아듣는 중(recognizing)인 명령을 취소합니다(cancelled). 이미 넘어간 명령이면 409."""
    try:
        return voice_listen_service.cancel_listen(request.voiceId)
    except voice_service.UnknownVoiceCommand as exc:
        raise HTTPException(status_code=404, detail="해당 voiceId를 찾을 수 없습니다.") from exc
    except voice_service.VoiceCommandError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


def _current_settings() -> VoiceSettings:
    # 호출어 상시 듣기(standby)는 다음 단계에서 붙습니다. 그전까지는 켜 두어도 기다리지 않습니다.
    return state_store.get_voice_settings().model_copy(update={"standby": False})


@router.get("/settings", response_model=VoiceSettings, tags=[TAG], summary="보드 음성 설정 조회")
def read_voice_settings() -> VoiceSettings:
    """wakeWord: 호출어(홈비스)로 부르기 · standby: 지금 호출어를 기다리는 중 · speak: 답변·위험 안내를 보드 스피커로 읽기"""
    return _current_settings()


@router.put("/settings", response_model=VoiceSettings, tags=[TAG], summary="보드 음성 설정 변경")
def update_voice_settings(request: VoiceSettingsUpdate) -> VoiceSettings:
    """보낸 항목만 바꿉니다. 바뀐 설정은 WebSocket voice.settings로 모든 화면에 알립니다."""
    state_store.update_voice_settings(wakeWord=request.wakeWord, speak=request.speak)
    current = _current_settings()
    ws_hub.broadcast_threadsafe("voice.settings", current.model_dump())
    return current
