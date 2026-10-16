"""
MongoDB 연결과 "쓰기 작업 큐"를 담당하는 모듈입니다.

동작 방식 (app/state_store.py와 함께 봐주세요):
- 읽기는 항상 서버 메모리에서 합니다. (DB가 멀리 있어도 API 응답이 느려지지 않도록)
- 쓰기는 메모리에 먼저 반영하고, 같은 내용을 이 모듈의 큐에 넣습니다.
  별도 스레드 하나가 큐에서 꺼내 순서대로 MongoDB에 저장합니다.
  -> MQTT 수신 스레드나 API 요청이 DB 때문에 멈추는 일이 없습니다.
- 서버가 시작될 때 DB에 저장된 내용을 메모리로 다시 불러옵니다. (재시작해도 데이터 유지)

MONGODB_URI가 비어 있거나 접속에 실패하면 DB 없이 메모리만으로 동작합니다.
이때는 서버를 재시작하면 데이터가 사라집니다. (/health 응답의 storage 값으로 확인 가능)
"""

import logging
import queue
import threading
from typing import Any, Callable, Optional

from app.config import settings

logger = logging.getLogger("induction.db")

# 컬렉션 이름 (docs/DB.md 의 설계와 1:1로 대응)
TELEMETRY_LATEST = "telemetry_latest"
TELEMETRY_LOGS = "telemetry_logs"
COMMANDS = "commands"
SAFETY_EVENTS = "safety_events"
SESSIONS = "sessions"
PRESENCE = "presence"
POLICIES = "policies"
CONTACTS = "contacts"
FALL_INCIDENTS = "fall_incidents"
RUNTIME_STATE = "runtime_state"
SMS_LOGS = "sms_logs"
DEVICE_STATES = "device_states"   # v0.3: 전등·정수기의 최신 상태
AI_DECISIONS = "ai_decisions"     # v0.3: AI 중앙 판정 엔진이 보낸 판단과 실행 결과

_client = None  # 이 모듈이 직접 만든 MongoClient (테스트에서 주입한 DB에는 없음)
_database = None
_queue: "queue.Queue[Callable[[Any], None]]" = queue.Queue(maxsize=10000)
_worker: Optional[threading.Thread] = None
_worker_lock = threading.Lock()


def is_enabled() -> bool:
    return _database is not None


def storage_name() -> str:
    return "mongodb" if is_enabled() else "memory"


def connect() -> None:
    """서버 시작 시 1번 호출. 실패해도 예외를 던지지 않고 메모리 모드로 남습니다."""
    global _client, _database

    if _database is not None:
        return  # 이미 연결됨 (또는 테스트에서 가짜 DB를 주입해 둠)

    if not settings.MONGODB_URI:
        logger.warning("MONGODB_URI가 비어 있어 DB 없이 메모리로만 동작합니다. (재시작 시 데이터 소실)")
        return

    try:
        from pymongo import MongoClient

        client = MongoClient(settings.MONGODB_URI, serverSelectionTimeoutMS=5000, connectTimeoutMS=5000)
        client.admin.command("ping")
    except Exception as exc:  # 접속 주소 오타, 허용 IP 미등록, 네트워크 차단 등
        logger.error("MongoDB 접속 실패 -> 메모리로만 동작합니다: %s", exc)
        return

    _client = client
    use_database(client[settings.MONGODB_DB])
    logger.info("MongoDB 연결 성공 (db=%s)", settings.MONGODB_DB)


def use_database(database) -> None:
    """사용할 DB 객체를 지정합니다. 테스트에서는 여기로 가짜 DB(mongomock)를 넣습니다."""
    global _database
    _database = database
    if database is not None:
        _ensure_indexes()


def disconnect() -> None:
    """서버 종료 시 호출. 큐에 남은 쓰기를 모두 저장한 뒤 연결을 닫습니다."""
    global _client, _database
    flush()
    if _client is not None:
        _client.close()
        _client = None
        _database = None


def _ensure_indexes() -> None:
    try:
        # 인덕션 상태 로그는 일정 기간이 지나면 MongoDB가 알아서 지웁니다 (TTL 인덱스).
        _database[TELEMETRY_LOGS].create_index(
            "receivedAt", expireAfterSeconds=settings.TELEMETRY_LOG_TTL_DAYS * 24 * 3600
        )
        _database[TELEMETRY_LOGS].create_index([("deviceId", 1), ("receivedAt", -1)])
        _database[SAFETY_EVENTS].create_index("seq")
        _database[COMMANDS].create_index("issuedAt")
        _database[SESSIONS].create_index("startedAt")
        _database[FALL_INCIDENTS].create_index("detectedAt")
        _database[SMS_LOGS].create_index("seq")
        _database[AI_DECISIONS].create_index("seq")
    except Exception:
        logger.exception("인덱스 생성 실패 (동작에는 지장 없음)")


# ---------------------------------------------------------------------------
# 쓰기: 큐에 넣고 바로 돌아옵니다
# ---------------------------------------------------------------------------

def upsert(collection: str, doc_id: str, document: dict) -> None:
    """_id가 같은 문서가 있으면 통째로 바꾸고, 없으면 새로 만듭니다."""
    if not is_enabled():
        return
    body = {k: v for k, v in document.items() if k != "_id"}
    _enqueue(lambda db: db[collection].replace_one({"_id": doc_id}, body, upsert=True))


def insert(collection: str, document: dict) -> None:
    """이력처럼 계속 쌓이는 문서를 추가합니다."""
    if not is_enabled():
        return
    body = dict(document)
    _enqueue(lambda db: db[collection].insert_one(body))


def _enqueue(operation: Callable[[Any], None]) -> None:
    _start_worker()
    try:
        _queue.put_nowait(operation)
    except queue.Full:
        logger.error("DB 쓰기 큐가 가득 차서 이번 쓰기를 버립니다. (DB 접속 상태를 확인하세요)")


def _start_worker() -> None:
    global _worker
    with _worker_lock:
        if _worker is None or not _worker.is_alive():
            _worker = threading.Thread(target=_run_worker, name="db-writer", daemon=True)
            _worker.start()


def _run_worker() -> None:
    while True:
        operation = _queue.get()
        try:
            database = _database
            if database is not None:
                operation(database)
        except Exception:
            logger.exception("DB 쓰기 실패 (메모리에는 반영되어 있음)")
        finally:
            _queue.task_done()


def flush() -> None:
    """큐에 쌓인 쓰기가 모두 끝날 때까지 기다립니다. (종료 시, 테스트에서 사용)"""
    _queue.join()


# ---------------------------------------------------------------------------
# 읽기: 서버 시작 시 메모리로 불러올 때만 사용합니다
# ---------------------------------------------------------------------------

def find_all(collection: str, sort_field: Optional[str] = None, newest_limit: Optional[int] = None) -> list[dict]:
    """컬렉션의 문서를 sort_field 오름차순으로 돌려줍니다.
    newest_limit을 주면 가장 최근 N개만 (그 N개 안에서는 오름차순으로) 돌려줍니다."""
    if not is_enabled():
        return []
    cursor = _database[collection].find({})
    if sort_field is not None:
        cursor = cursor.sort(sort_field, -1)
        if newest_limit is not None:
            cursor = cursor.limit(newest_limit)
        return list(reversed(list(cursor)))
    return list(cursor)
