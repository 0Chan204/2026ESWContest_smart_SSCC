"""
AI 중앙 판정 엔진이 호출하는 REST API입니다. (v0.3, Swagger 섹션: AI 중앙 제어)

- GET  /ai/device-states      판단에 쓸 기기 상태 조회
- POST /ai/decisions          판단 결과 전송 -> 서버가 가전 제어 + 기록
- GET  /ai/decisions          판단 기록과 사용자 피드백 조회 (가중치 조정용)
- GET  /ai/decisions/{id}     판단 1건 조회
"""

from fastapi import APIRouter, HTTPException, Response, status

from app import ai_service, state_store
from app.schemas import (
    AiDecisionAccepted,
    AiDecisionListResponse,
    AiDecisionRecord,
    AiDecisionRequest,
    DeviceListResponse,
)

TAG = "AI 중앙 제어"
router = APIRouter(prefix="/ai")


@router.get("/device-states", response_model=DeviceListResponse, tags=[TAG], summary="기기 상태 조회 (판정 엔진 입력용)")
def read_device_states() -> DeviceListResponse:
    """인덕션·전등·정수기의 현재 상태를 돌려줍니다.
    control_state는 마지막으로 상태를 바꾼 주체입니다 (user: 사용자, homevis: HomeVIS 자동 제어)."""
    return DeviceListResponse(items=ai_service.get_device_states())


@router.post("/decisions", response_model=AiDecisionAccepted, status_code=status.HTTP_202_ACCEPTED, tags=[TAG], summary="판단 결과 전송 (판정 엔진 → 서버)")
def receive_decision(request: AiDecisionRequest, response: Response) -> AiDecisionAccepted:
    """
    판정 엔진의 판단 결과를 받아 actions에 적힌 가전 제어를 실행하고 기록합니다.

    - 같은 decisionId로 다시 보내면 다시 실행하지 않고 처음 결과를 돌려줍니다 (duplicate=true, 200).
      네트워크가 불안해서 재전송하는 경우를 위한 동작입니다.
    - 제어 일부가 실패해도 나머지는 실행하며, 각 제어의 결과는 actions[].status로 확인합니다.
      (sent: 전송함, rejected: 실행 조건이 안 맞아 거부, failed: 전송 실패)
    - scenario가 fall_detected면 낙상 처리 흐름을 실행합니다: 인덕션 비상 차단 + 전등 깜빡임 ->
      사용자 문자 -> (응답 없으면) 보호자 문자 -> (응답 없으면) 자동 신고.
      인덕션 turn_off / 전등 blink는 서버가 직접 실행하므로 actions에 넣지 않아도 됩니다.
    - 인덕션 restore_power는 HomeVIS가 끄거나 낮추기 직전의 화력으로 다시 켭니다.
    - 정수기 dispense에는 출수량(amountMl)이 필요합니다. 전등 blink 시간을 비우면 10초입니다.
    - announcement를 보내면 대시보드에 WebSocket(ai.announcement)으로 전달하고, 대시보드가 화면 표시 + 음성 안내를 합니다.
      제어 없이 안내만 보내도 됩니다 (actions 비움). 날씨는 GET /weather로 가져가 문장에 넣으세요.
    - expiresAt이 지난 뒤 도착한 판단은 실행하지 않고 status=expired로 기록합니다 (응답은 그대로 202).
      낙상(fall_detected)은 늦게 도착해도 안전을 위해 항상 실행합니다.
    """
    record, duplicate = ai_service.handle_decision(request)
    if duplicate:
        response.status_code = status.HTTP_200_OK
    return AiDecisionAccepted(**record.model_dump(), duplicate=duplicate)


@router.get("/decisions", response_model=AiDecisionListResponse, tags=[TAG], summary="판단 기록 목록 조회")
def list_decisions(limit: int = 50) -> AiDecisionListResponse:
    """최신순. 사용자가 해당 판단의 안전 이벤트에 피드백을 남겼다면 feedback에 함께 들어 있습니다."""
    records = state_store.list_ai_decisions()
    newest_first = list(reversed(records))[: max(limit, 0)]
    return AiDecisionListResponse(items=newest_first, total=len(records))


@router.get("/decisions/{decision_id}", response_model=AiDecisionRecord, tags=[TAG], summary="판단 기록 단건 조회")
def read_decision(decision_id: str) -> AiDecisionRecord:
    record = state_store.get_ai_decision(decision_id)
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="해당 decisionId를 찾을 수 없습니다.")
    return record
