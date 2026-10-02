"""
WebSocket /stream 연결들을 관리하고, 모든 실시간 이벤트를 브로드캐스트하는 허브입니다.

주의: MQTT 콜백(_on_message)은 asyncio 이벤트 루프가 아니라 paho-mqtt의
백그라운드 스레드에서 실행됩니다. 그래서 그쪽에서 바로 `await`를 할 수 없고,
`asyncio.run_coroutine_threadsafe`로 메인 이벤트 루프에 작업을 넘겨줘야 합니다.
REST 핸들러(presence, 화구 제어 등)는 이미 이벤트 루프 안에서 실행되지만,
코드 경로를 하나로 통일하기 위해 어디서든 `broadcast_threadsafe`만 쓰면 됩니다.
"""

import asyncio
import json
import logging
from datetime import datetime, timezone

from fastapi import WebSocket

logger = logging.getLogger("induction.ws")


class ConnectionManager:
    def __init__(self) -> None:
        self._connections: set[WebSocket] = set()
        self._lock = asyncio.Lock()

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        async with self._lock:
            self._connections.add(ws)

    async def disconnect(self, ws: WebSocket) -> None:
        async with self._lock:
            self._connections.discard(ws)

    async def broadcast(self, event: str, data: dict) -> None:
        envelope = {
            "event": event,
            "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "data": data,
        }
        message = json.dumps(envelope, ensure_ascii=False, default=str)

        async with self._lock:
            targets = list(self._connections)

        for ws in targets:
            try:
                await ws.send_text(message)
            except Exception:
                logger.info("연결이 끊긴 WebSocket 클라이언트를 정리합니다.")
                await self.disconnect(ws)

    async def send_to(self, ws: WebSocket, event: str, data: dict) -> None:
        envelope = {
            "event": event,
            "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "data": data,
        }
        await ws.send_text(json.dumps(envelope, ensure_ascii=False, default=str))


manager = ConnectionManager()

_loop: asyncio.AbstractEventLoop | None = None


def bind_loop(loop: asyncio.AbstractEventLoop) -> None:
    """main.py의 lifespan에서 서버 시작 시 1번 호출: 현재 실행 중인 이벤트 루프를 기억해둡니다."""
    global _loop
    _loop = loop


def broadcast_threadsafe(event: str, data: dict) -> None:
    """MQTT 스레드/동기 코드에서도 안전하게 브로드캐스트를 예약할 수 있는 함수."""
    if _loop is None:
        logger.warning("이벤트 루프가 아직 바인딩되지 않아 브로드캐스트를 건너뜁니다: %s", event)
        return
    asyncio.run_coroutine_threadsafe(manager.broadcast(event, data), _loop)


def run_coroutine_threadsafe(coro) -> "asyncio.Future | None":
    """동기 코드(FastAPI의 sync 라우터 등)에서 지연 실행이 필요한 코루틴(예: 낙상 사고
    자동 신고 타이머)을 메인 이벤트 루프에 예약할 때 사용하는 범용 헬퍼입니다."""
    if _loop is None:
        logger.warning("이벤트 루프가 아직 바인딩되지 않아 작업 예약을 건너뜁니다.")
        return None
    return asyncio.run_coroutine_threadsafe(coro, _loop)
