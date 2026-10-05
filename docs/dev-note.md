# 개발노트 — 인덕션 백엔드

작성일: 2026-09-03 · 최종 업데이트: 2026-09-30 (v0.2: 프론트/임베디드 팀 API 명세 확정 반영) · 담당: 백엔드(인덕션)

## 구성

- 백엔드: Python 3.13 / FastAPI 0.115.0 / uvicorn
- MQTT 브로커: Mosquitto 2.1.2, 로컬 1883 포트
- MQTT 클라이언트: paho-mqtt 1.6.1
- 서버 주소: 127.0.0.1:8000, REST 기본 경로: `/api/v1`
- DB: MongoDB Atlas (무료 등급). 읽기는 메모리, 쓰기는 메모리+DB. 시작 시 DB에서 불러옴. 구조는 `docs/DB.md`

## v0.2 변경 요약

- 화구 2개(`element_1`/`element_2`) → 화구 1개, `burners[]` 배열 구조
- 필드명 snake_case → camelCase
- 화구 상태 `on/off/overheat` → `deviceState`: `off/on/overheated/cooling`
- 명령 처리 확인: 별도 MQTT ack 토픽 추가 (팀 확정안, REST ack 아님)
- "오프라인" 판정: 별도 heartbeat 메시지 없이 telemetry 미수신 시간(15초)으로 판단
- 안전 이벤트, 조리 세션, 부재중 자동 제어 정책, WebSocket 실시간 스트림 신규 추가
- Swagger 문서는 `/docs` 하나로 통합하고 기능별 태그(회원 정보 / 낙상 사고 감지 / AI 재실 판단 / 인덕션 제어 / 대시보드 화면 / 안전 이벤트)로 섹션 구분

## MQTT

- telemetry(상태) 토픽: `home/kitchen/induction/{device_id}/state` — 가전이 발행, 서버가 구독
  - 발행 주기: 3초 + 상태 변경(명령 적용/사용자 조작/과열 등) 발생 시 즉시 추가 발행
- ack(명령 처리 결과) 토픽: `home/kitchen/induction/{device_id}/ack` — 가전이 발행, 서버가 구독 (v0.2 신규)
- command(제어) 토픽: `home/kitchen/induction/{device_id}/command` — 서버가 발행, 가전이 구독
- QoS 1, retain 미사용
- 기기 식별자: `induction-01`, 화구 식별자: `burner-1`

## API

Swagger: `/docs` (기능별 섹션으로 구분). 실제 경로는 전부 `/api/v1` 하위.

**인덕션(디바이스) — 서버가 캐시한 값 조회용 (가전 자체는 MQTT만 사용)**
- `GET /api/v1/devices/{deviceId}/telemetry` — 마지막 수신 telemetry. 수신 이력 없으면 404
- `GET /api/v1/devices/{deviceId}/status` — 온라인/오프라인 여부

**프론트 대시보드 / AI 모델**
- `POST /api/v1/presence` — AI 재실 판단 모델이 관찰 사실 보고 (조치는 서버가 결정)
- `GET /api/v1/snapshot` — 초기 전체 상태
- `POST /api/v1/appliances/{id}/burners/{burnerId}/commands` — 화구 제어 (사용자/시스템 명령 공통 창구). 과열 시 409
- `GET /api/v1/commands/{commandId}` — 명령 상태 조회 (WS 대체용)
- `GET /api/v1/safety-events`, `GET /api/v1/safety-events/{eventId}`, `POST /api/v1/safety-events/{eventId}/feedback`
- `GET /api/v1/sessions/{sessionId}` — 조리 세션 타임라인
- `GET/PUT /api/v1/policies/kitchen-absence` — 부재중 안전 정책 (코드에 안 박고 API로 튜닝)
- `WSS /api/v1/stream` — 실시간 이벤트. `?since={lastEventId}`로 재연결 시 놓친 safety.event만 재전송
- `GET /health`

## 적용된 규칙

- 화구가 `overheated` 상태면 `turn_on` 및 `set_level`(화력 지정) 명령을 거부함. `turn_off`만 허용
- 제어 명령 JSON에는 지정된 항목만 포함함 (미지정 필드는 제외)
- `commandId` 형식: `cmd-YYYYMMDD-{8자리}`
- 명령 적용 여부는 가전이 보내는 별도 ack 메시지(`result: applied/rejected/failed`)로 확정함
  (팀 확정안 — telemetry 재사용안 대신 채택)
- 부재중 정책(기본값): watch 60초 / reduce 180초(화력 1단으로) / off 600초, `zone=near`면 임계값 2배
- 과열 임계값(팀 확정): 진입 150℃ / 해제 60℃

## 시뮬레이터 (`tests/simulate_device.py`)

실물 하드웨어 대체용으로 사용 중. (v0.2: 화구 1개, camelCase, ack 발행 반영)

- 3초마다 telemetry 발행 (명령 적용 직후에는 즉시 한 번 더 추가 발행)
- 실온 25℃ 기준, 화력 1단당 1틱에 1.5℃ 상승
- 150℃ 도달 시 `overheated`로 전환되고 level 0이 됨
- 60℃ 이하로 내려가면 `off`로 자동 복귀
- `turn_off` 수신 시 아직 실온+5℃ 초과로 뜨거우면 `cooling`을 거쳐 `off`로 전환
- 명령 처리 후 ack 토픽으로 `applied`/`rejected` 결과를 발행

## DB

- 관계형 ERD(테이블 9개)는 폐기하고 MongoDB 컬렉션 설계로 대체함. 상세는 `docs/DB.md`
- 컬렉션 10개: `contacts`, `policies`, `telemetry_latest`, `telemetry_logs`, `commands`, `safety_events`, `sessions`, `presence`, `fall_incidents`, `runtime_state`
- 인덕션 상태 로그(`telemetry_logs`)는 7일 후 자동 삭제

## 동작 확인된 범위 (Cowork 세션 내 TestClient 기반 스모크 테스트)

- FastAPI 앱 임포트/라우팅/순환참조 없음 확인
- telemetry 수신 → 조회(200), 온라인 판정
- 화구 제어(REST) → MQTT 발행(모킹) → ack 반영 → 명령 상태 `pending → sent → acked` 전이 확인
- 과열 telemetry 수신 시 `overheat_detected` 안전 이벤트 생성, 이후 `turn_on` 시도 시 409 + `command_blocked` 이벤트 확인
- 재실 판단(presence) 낮은 신뢰도 → 조치 없음 / 장시간 이탈 → `auto_power_off` 자동 명령 + 이벤트 발생 확인
- `/docs` Swagger 문서 및 기능별 태그 구분 정상 생성 확인
- 실제 Mosquitto 브로커 연동은 이 작업 환경에 mosquitto가 없어 재검증하지 못했음 — 로컬/GCP 환경에서
  `python tests/simulate_device.py` + uvicorn으로 최종 확인 필요

## 미연동 항목

- 실물 임베디드 (ESP32 / Pico W) — ack 토픽 발행 로직 신규 반영 필요
- 프론트엔드 실연동 (현재는 API 명세 기준 목업/스모크 테스트만 완료)
- 실제 AI 재실 판단 모델 (현재는 presence 엔드포인트를 curl로 흉내)
- DB (제품 미확정)
- MQTT 인증 (현재 `allow_anonymous true`)
- ERD/DDL의 화구 1개 반영 및 v0.2 스키마(안전 이벤트/세션/정책) 테이블 설계
