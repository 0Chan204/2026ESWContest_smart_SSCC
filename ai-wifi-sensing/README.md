# HomeVIS Wi-Fi 센싱

실시간 센싱·재실/행동 추론과 CSI 학습 데이터 수집 코드를 관리합니다.

| 폴더 / 문서 | 역할 |
| --- | --- |
| [pi](pi/) | Raspberry Pi의 CSI 시리얼 수신·특징 추출·MQTT 전송 |
| [server](server/) | 재실·행동 모델 추론과 백엔드 연동 |
| [model](model/) | 재실·행동 모델 학습 |
| [board](board/README.md) | ATLAS 보드의 추론 서버 배포 |
| [collection](collection/README.md) | 노트북 USB 직결·Pi 에이전트 기반 데이터 수집·저장·시각화 |
| [CSI 펌웨어](../embedded/wifi-sensing/README.md) | ESP32-C6 수집용 AP·CSI 수신기 |
| [RUN_GUIDE.md](RUN_GUIDE.md) | 기존 실시간 재실·행동 추론 실행 순서 |

수집 도구의 `collection/pi_agent`는 데이터 저장용 C 에이전트입니다. 실시간 MQTT 특징 전송용 `pi/edge_node.py`와 실행 목적이 다릅니다. 수집 시 USB 포트를 동시에 사용하는 시리얼 모니터·실시간 프로그램은 종료해 주세요.

CSI 수집 코드 이관 범위와 변경 단위별 커밋 제목·본문은 [collection/COMMIT_GUIDE.md](collection/COMMIT_GUIDE.md)에 정리했습니다.
