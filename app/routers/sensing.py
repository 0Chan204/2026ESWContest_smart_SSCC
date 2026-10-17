"""
최종 재실 판단 결과 조회 (v0.4). AI 중앙 판정 엔진이 HTTP로 꺼내 씁니다.
결과는 재실 판단 담당이 MQTT(home/edge/result)로 보내고, 서버는 판단 없이 저장된 값을 그대로 돌려줍니다.
실제 로직은 app/edge_service.py에 있습니다.
"""

from typing import Optional

from fastapi import APIRouter, HTTPException, Query, status

from app import edge_service, state_store
from app.schemas import SensingResult, SensingResultListResponse

router = APIRouter(prefix="/sensing")
TAG = "AI 중앙 제어"


@router.get("/results/latest", response_model=SensingResult, tags=[TAG], summary="최신 최종 재실 판단 결과")
def read_latest_result() -> SensingResult:
    """
    재실 판단 담당이 보낸 가장 최근 결과를 그대로 돌려줍니다. 아직 받은 결과가 없으면 404입니다.
    결과가 얼마나 오래됐는지(observedAt, validSec)는 받는 쪽에서 판단합니다.
    """
    result = state_store.get_latest_sensing_result()
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="아직 받은 최종 판단 결과가 없습니다.")
    return result


@router.get("/results", response_model=SensingResultListResponse, tags=[TAG], summary="기간별 최종 재실 판단 결과")
def read_results(
    since: Optional[str] = Query(default=None, description="이 시각 이후 (observedAt 기준, ISO 8601)"),
    until: Optional[str] = Query(default=None, description="이 시각 이전 (observedAt 기준, ISO 8601)"),
    limit: int = Query(default=500, ge=1, le=state_store.SENSING_RESULT_MEMORY_LIMIT),
) -> SensingResultListResponse:
    """
    조건에 맞는 결과 중 최근 limit개를 오래된 것부터 돌려줍니다.
    서버 메모리에 있는 최근 5000건(1초마다 오면 약 1시간 20분) 안에서 찾습니다.
    """
    try:
        items, total = edge_service.query_results(since, until, limit)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="since / until은 ISO 8601 시각이어야 합니다. 예: 2026-10-17T12:00:00+00:00",
        ) from exc
    return SensingResultListResponse(items=items, total=total)


@router.get("/combined", tags=[TAG], summary="엣지 노드 합친 메시지 미리보기")
def read_combined() -> dict:
    """
    지금 시점의 합친 엣지 메시지(home/edge/combined로 보내는 것과 같은 형식)를 보여줍니다. 확인·디버깅용입니다.
    형식: {"seq", "publishedAt", "locations": {구역: {"node": 노드가 보낸 최신 메시지 또는 null}}}
    이 요청은 MQTT로 발행하지 않고, seq도 올리지 않습니다 (마지막으로 발행한 seq를 보여줌).
    """
    return edge_service.build_combined(advance_seq=False)
