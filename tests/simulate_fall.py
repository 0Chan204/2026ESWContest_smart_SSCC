"""
낙상 감지 AI 모델이 아직 준비되지 않았을 때, 그 자리를 대신해서
POST /api/v1/safety/fall-events 를 호출해보는 테스트 스크립트입니다.

사용 방법:
    # 1) 서버가 떠 있는 상태에서 (uvicorn app.main:app --reload)
    # 2) 보호자 연락처를 먼저 등록해두면 실제 SMS 발송까지 확인 가능:
    #    curl -X PUT http://localhost:8000/api/v1/guardian \
    #      -H "Content-Type: application/json" \
    #      -d '{"name": "보호자", "phone": "01000000000"}'
    # 3) 이 스크립트 실행:
    python tests/simulate_fall.py

실행하면:
- 낙상 이벤트 1건을 서버로 보내고, 응답으로 받은 confirmUrl(확인 링크)을 출력합니다.
- 서버 로그에서 "인덕션 비상 전원 차단"과 "SMS 발송(또는 미설정 경고)"을 확인할 수 있습니다.
- 정책(policies/fall-safety)의 autoReportSec(기본 60초) 안에 아무 응답이 없으면
  서버가 자동으로 '신고' 처리합니다. 그 전에 직접 해결/신고를 호출해볼 수도 있습니다.
"""

import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import requests

sys.path.append(str(Path(__file__).resolve().parent.parent))

from app.config import settings  # noqa: E402

BASE_URL = "http://localhost:8000" + settings.API_PREFIX


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def main() -> None:
    report = {
        "room": settings.KITCHEN_ROOM,
        "confidence": 0.93,
        "observedAt": now_iso(),
        "modelVersion": "fall-detector-sim-0.1",
    }
    res = requests.post(f"{BASE_URL}/safety/fall-events", json=report, timeout=5)
    res.raise_for_status()
    accepted = res.json()
    print("낙상 이벤트 접수됨:", accepted)

    confirm_url = accepted["confirmUrl"]
    parsed = urlparse(confirm_url)
    token = parse_qs(parsed.query)["token"][0]
    incident_id = accepted["incidentId"]

    print(f"\n확인 링크: {confirm_url}")
    print(f"incidentId={incident_id}  token={token}")
    print(
        "\n이 사건을 지금 바로 '해결' 처리하려면:\n"
        f"  curl -X POST '{BASE_URL}/fall-incidents/{incident_id}/resolve?token={token}'\n"
        "'신고' 처리하려면:\n"
        f"  curl -X POST '{BASE_URL}/fall-incidents/{incident_id}/report?token={token}'\n"
        "아무 것도 하지 않으면 policies/fall-safety의 autoReportSec 뒤에 서버가 자동으로 신고 처리합니다."
    )


if __name__ == "__main__":
    main()
