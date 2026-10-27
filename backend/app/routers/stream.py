"""
실시간 이벤트를 내보내는 WebSocket 엔드포인트입니다.

모든 메시지는 { event, at, data } 봉투 형식을 따릅니다 (app/ws_hub.py 참고).
재연결 시 ?since={lastEventId} 쿼리로 놓친 safety.event만 재전송합니다.
(telemetry는 재전송하지 않습니다 - 최신값만 의미가 있으므로)
"""

import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app import state_store, ws_hub

logger = logging.getLogger("induction.stream")

router = APIRouter(tags=["dashboard"])


@router.websocket("/stream")
async def stream(websocket: WebSocket) -> None:
    since = websocket.query_params.get("since")

    await ws_hub.manager.connect(websocket)
    logger.info("WebSocket 클라이언트 연결됨 (since=%s)", since)

    try:
        if since:
            missed = state_store.list_safety_events(after_event_id=since)
            for event in missed:
                await ws_hub.manager.send_to(websocket, "safety.event", event.model_dump())

        while True:
            # 클라이언트 -> 서버로는 별도 메시지를 받지 않지만, 연결 유지를 위해 수신 대기합니다.
            await websocket.receive_text()
    except WebSocketDisconnect:
        logger.info("WebSocket 클라이언트 연결 종료")
    finally:
        await ws_hub.manager.disconnect(websocket)
