# 실시간 중앙 판단 설계 및 적용 내역

최종 Wi-Fi 위치 JSON과 백엔드 클라이언트는 [통합 문서](backend_integration.md)를 참고하세요.
해당 경로는 원본 null/reason, 관측 유효성, 측정 시각을 보존하며 미측정 행동을 만들지 않습니다.
직접 호출의 unknown 유예와 별도로 `observation_valid=False` 입력은 즉시 불확실하게 처리합니다.
마지막 확인 위치와 현재 관측의 유효성(`observation_valid`, `sensing_status`)을 함께 확인해야 합니다.

> 이 문서의 `action`은 기존 알림/위험 상태 출력이다. 화력·전등 자동 제어 명령은
> [Confidence 기반 자동 제어](confidence_control.md)의 점수·threshold 경로에서 별도로 생성한다.

## 기존 코드와 변경 범위

기존 `CentralController.evaluate(SensingState, DeviceState)`와 `RuleBasedDecisionEngine`은 단건 판단 API로 그대로 유지한다. 기존 `KITCHEN → LOW` 규칙도 바꾸지 않는다. 새 실시간 API에서는 요구사항에 따라 확인된 `kitchen → NORMAL`을 적용한다. 두 API의 상태는 독립적이므로 실시간 시스템은 `update_sensing`, `update_appliance`, `tick`을 사용한다.

| 파일 | 변경 이유 |
| --- | --- |
| src/control/central_controller.py | 기존 evaluate를 유지하며 실시간 엔진 위임 메서드 추가 |
| src/control/__init__.py | 새 입력 모델 및 설정 공개 |
| src/models.py | RiskDecision에 선택적 decision_context 추가; 기존 출력 키는 유지 |
| src/control/realtime_config.py | 시간·confidence·출력·온도·상승률·상태별 점수/액션 설정 |
| src/control/realtime_models.py | 실시간 입력 검증, 상태 및 결과 직렬화, 기존 RiskDecision 변환 |
| src/control/decision/realtime.py | 시간 추적과 상태 전이 구현 |
| test_realtime.py | 순서 있는 JSONL 입력 및 기존 LLM/TTS 연결 예제 |
| tests/test_realtime_controller.py | 시간 경계, 센서 오류, 긴급 상황, 호환성 검증 |
| README.md / 이 문서 | 실행법과 정책 및 시나리오 명시 |

LLM adapter, message generator, prompts, TTS, AlertService, 기존 test_alert.py는 변경하지 않았다. 새 필드는 기존 프롬프트 직렬화를 통해 LLM에 전달된다.

## 1. 전체 동작 흐름

외부 Wi-Fi Sensing/기기 모듈 → 입력 모델 검증 → 위치 후보 확인 및 시간 추적 → 긴급 신호 우선 판단 → 상태 결정 → RealtimeDecision → to_risk_decision() → 기존 AlertService → 기존 LLM/fallback → 기존 TTS.

하나의 컨트롤러 인스턴스는 한 가정의 한 사용자/조리기기 조합을 담당한다. 호출은 직렬화해야 한다. 네트워크 수신, 실제 Wi-Fi 분석, 기기 통신은 외부 모듈이 담당한다. 연결 규격이 주어지면 이 API로 전달하면 된다.

## 2. 입력 구조

`SensingUpdate(location, timestamp, activity="unknown", confidence=1.0, detected=True)`

- location: kitchen, living_room, bedroom, entrance, outside, unknown
- activity: 행동 원문을 수용한다. 현재 위험 규칙에서는 행동별 추가 위험을 추정하지 않는다.
- confidence: 0~1. MIN_CONFIDENCE 미만은 불확실한 관측이다.
- detected=False: 센서가 정상적으로 보고한 사용자 미감지 신호이다. 통신 단절과 다르다.

`ApplianceUpdate(power_on, timestamp, power_watts=None, temperature_c=None, operating=None, smoke=False, fire=False, abnormal=False)`

- 원시 출력 단위는 W, 온도는 °C이다. 기기 출력이 %나 다른 단위라면 수신 어댑터에서 변환한다.
- active는 power_on이 True이고 operating이 False가 아닐 때이다. operating 생략 시 power_on을 따른다.
- 정상 가스 불꽃과 화재는 다르다. fire에는 기기가 판정한 화재/비정상 불꽃 신호를 넣는다.
- 수치 누락은 허용하지만 수치가 있으면 유한해야 하며 출력은 음수가 될 수 없다.

timestamp는 공통 기준의 초 단위 숫자이다. Unix 초 또는 공통 시작점 기준 경과 초를 사용한다. 스트림별 중복·역순, 마지막 평가보다 과거인 이벤트는 ValueError로 거부한다. 서로 다른 스트림의 같은 시각은 허용한다. 지연 이벤트가 있으면 외부 수신부에서 정렬한 뒤 전달한다.

## 3. 상태 정의 및 기존 알림 매핑

| 상태 | 의미 | action | 기존 알림 단계 |
| --- | --- | --- | --- |
| NORMAL | 확인된 정상 조리 또는 기기 종료 | NONE | NORMAL |
| TEMPORARY_ABSENCE | 짧은 주방 이탈 | NONE | NORMAL |
| CAUTION | 주방 이탈 주의 | VOICE_WARNING | WARNING |
| WARNING | 장기 이탈, 현관 체류, 불확실한 고출력 상태 | VOICE_WARNING | WARNING |
| DANGER | 장시간 이탈, 외출, 긴급 위험 | EMERGENCY_WARNING | HIGH |
| SENSOR_UNCERTAIN | 센싱/기기 상태 확인 필요 | CHECK_SENSOR | WARNING |
| RECOVERED | WARNING/DANGER 해제 후 한 번 출력하는 복귀 상태 | NONE | NORMAL |

CHECK_SENSOR도 기존 WARNING 음성 정책을 사용한다. 실제 기기 제어나 경고음 재생은 하지 않는다. 점수는 정책의 심각도 표현이며 사고 확률이 아니다.

## 4. 구체적인 상태 판단 우선순위

1. 연기·화재·기기 이상 또는 신뢰 가능한 연속 기기 관측의 급격한 온도 상승 → DANGER. 전원이 OFF여도 우선한다.
2. 최신 기기 상태가 종료 → NORMAL, 직전 WARNING/DANGER라면 RECOVERED.
3. 마지막 기기 상태가 동작 중이고 외출 확정 또는 이탈 시간이 DANGER 기준 이상 → DANGER.
4. 센싱/기기 불확실 → SENSOR_UNCERTAIN. 마지막 기기가 동작 중이고 출력/온도가 높으면 WARNING. 이미 확정된 WARNING/DANGER는 불확실성만으로 낮추지 않는다.
5. 확인된 kitchen → NORMAL. 현관 체류 확인 → WARNING.
6. 나머지 위치는 이탈 시간과 출력/온도 상승을 함께 평가한다.

초기 위치는 unknown이다. 첫 kitchen 관측도 확인 시간이 필요하다. 초기 기기 입력이 없으면 정상으로 간주하지 않는다.

## 5. 주방 이탈 시간

| 경과 시간 | 기본 상태 |
| --- | --- |
| KITCHEN_SHORT_ABSENCE 미만 | TEMPORARY_ABSENCE |
| KITCHEN_SHORT_ABSENCE 이상, KITCHEN_WARNING_TIME 미만 | CAUTION |
| KITCHEN_WARNING_TIME 이상, KITCHEN_DANGER_TIME 미만 | WARNING |
| KITCHEN_DANGER_TIME 이상 | DANGER |

기본값은 각각 20, 40, 60초이다. 프로그램 시작 시각이 아니라 엔진이 추적하는 주방 이탈 경과시간을 기준으로 한다. 새 위치는 SENSING_CONFIRM_TIME(5초) 이상 관측되어야 인정한다. 확인 후 이탈 시작은 해당 후보를 처음 관측한 시각으로 기록하여 확인 대기 시간을 빠뜨리지 않는다. 다른 방끼리 이동해도 주방 이탈 타이머는 초기화하지 않는다. 기기 OFF 중에도 실제 위치 이탈 시간은 유지하지만 위험 상태는 해제한다.

이 시간은 위험 상태 기준이며 화력 감소의 강제 실행 시간이 아니다. 이탈 시간 feature는 별도의
`KITCHEN_LEAVE_FULL_SECONDS=60.0`에서 최대가 되고, 실제 `reduce_power`는 기존 confidence
threshold 0.82와 센싱·기기 유효성 및 중복 방지 조건으로 결정한다.

## 6. 집 밖 이탈

신뢰 가능한 outside 관측이 max(SENSING_CONFIRM_TIME, OUTSIDE_CONFIRM_TIME) 이상 이어져야 확정한다. 기본 10초이다. detected=False, 신뢰도 낮음, unknown, 다른 위치가 끼면 후보 확인을 다시 시작한다. 미감지만으로 외출을 확정하지 않는다. 현관은 max(SENSING_CONFIRM_TIME, ENTRANCE_CONFIRM_TIME) 이상 이어지면 WARNING이며, 현관만으로 외출 확정하지 않는다.

tick만으로 단일 outside 관측을 확정하지 않는다. 센서 업데이트 간격이 UNKNOWN_TIMEOUT 이상이면 새 후보로 다시 시작한다. 외출 확인 후 데이터가 끊겨도 외출 확정 상태를 임의로 해제하지 않는다.

## 7. 주방 복귀

kitchen 관측이 max(SENSING_CONFIRM_TIME, RETURN_CONFIRM_TIME) 이상 이어지면 이탈 시간을 초기화한다. 이전 WARNING/DANGER가 해제되면 RECOVERED를 한 평가 결과에 출력하고 다음 정상 평가에서 NORMAL이 된다. 긴급 신호가 남아 있으면 복귀해도 DANGER이다. 같은 시각의 기기·센서 이벤트도 각각 평가하므로 호출자는 각 반환 결과를 처리해야 한다.

## 8. unknown 및 통신 오류

unknown/낮은 confidence 관측은 UNKNOWN_TIMEOUT(20초) 미만 동안 마지막 확정 위치를 유지한다. 이탈 시간은 계속 진행한다. 20초 이상이면 불확실 상태로 처리한다. 센서가 전혀 오지 않아도 마지막 업데이트 후 20초에 동일하게 처리한다. 기기 데이터는 APPLIANCE_TIMEOUT(20초) 이후 stale이다. 마지막 OFF 상태가 오래되었다면 현재 안전하다고 단정하지 않는다.

`tick(now)`를 외부 이벤트 루프에서 주기적으로 호출해야 무입력 시간도 평가된다. tick 시간과 이벤트 시간은 같은 시계를 사용한다. JSONL 재생 중 통신 단절은 tick 이벤트를 넣어 재현한다. 실제 운영용 스케줄러/백그라운드 스레드는 이 모듈이 생성하지 않는다.

## 9. 출력·온도·변화율

HIGH_POWER_WATTS=1800 또는 HIGH_TEMPERATURE_C=200 이상을 높은 출력/온도로 본다. 연속 기기 관측 차이/시간으로 출력 및 온도 상승률을 계산한다. RISING_POWER_WATTS_PER_SECOND=100 또는 RISING_TEMPERATURE_C_PER_SECOND=1 이상이면 상승 중으로 본다. 높은 출력/온도와 상승 조건을 모두 만족하면 CAUTION 구간을 WARNING, WARNING 구간을 DANGER로 높인다.

RAPID_TEMPERATURE_C_PER_SECOND=10 이상이면 즉시 DANGER이다. 누락된 수치나 APPLIANCE_TIMEOUT 이상 떨어진 관측으로는 상승률을 추정하지 않는다. 이는 프로토타입의 두 관측 간 변화율이며 장기 추세 모델은 아니다. 모든 기준은 RealtimeConfig에서 장비에 맞게 조정한다.

## 10. 상태 전이 및 내부 저장값

| 이전 상태 | 조건 | 다음 상태 |
| --- | --- | --- |
| 모든 상태 | 긴급 위험 신호 | DANGER |
| NORMAL | 주방 이탈 확인, 짧은 이탈 | TEMPORARY_ABSENCE |
| TEMPORARY_ABSENCE | 짧은 이탈 기준 도달 | CAUTION |
| CAUTION | 경고 기준 도달 | WARNING |
| WARNING | 위험 기준 도달/외출 확정 | DANGER |
| WARNING/DANGER | 주방 복귀 확인 또는 기기 종료, 긴급 신호 없음 | RECOVERED |
| RECOVERED | 정상 조건 유지 | NORMAL |
| NORMAL/TEMPORARY_ABSENCE/CAUTION | 데이터 불확실 | SENSOR_UNCERTAIN 또는 고출력 WARNING |
| WARNING/DANGER | 데이터 불확실 | 기존 심각도 유지 또는 더 높은 위험 |
| SENSOR_UNCERTAIN | 입력 회복 | 현재 조건으로 재평가 |

엔진은 current_state, previous_state, last_user_location, kitchen_exit_time, outside_start_time, current_absence_duration, last_sensor_update, last_appliance_update, appliance_operating_duration과 위치 후보/시작 시각을 저장한다. 운영 시간은 마지막 알려진 ON을 기준으로 한 경과 시간이며, 통신 단절 동안 실제 동작을 보증하지 않는다. 상태는 메모리에 있고 재시작하면 초기화된다.

## 11. 구체적인 시나리오

별도 표기가 없으면 신뢰 가능한 최신 관측, 위치 확인 완료, 출력/온도는 일정하다. 초는 후보 첫 관측부터의 이탈 시간이다.

| 이전 위치 | 현재 위치 | 기기 | 출력 W / 온도 °C | 이탈 초 | 판단 상태 | 이유 | action |
| --- | --- | --- | --- | --- | --- | --- | --- |
| kitchen | kitchen | ON | 800 / 90 | 0 | NORMAL | 정상 조리 | NONE |
| kitchen | living_room | ON | 800 / 90 | 5 | TEMPORARY_ABSENCE | 짧은 이탈 | NONE |
| kitchen | bedroom | ON | 800 / 90 | 19 | TEMPORARY_ABSENCE | 20초 미만 | NONE |
| living_room | living_room | ON | 800 / 90 | 20 | CAUTION | 주의 기준 도달 | VOICE_WARNING |
| living_room | bedroom | ON | 800 / 90 | 39 | CAUTION | 다른 방 이동도 누적 | VOICE_WARNING |
| bedroom | bedroom | ON | 800 / 90 | 40 | WARNING | 경고 기준 도달 | VOICE_WARNING |
| bedroom | bedroom | ON | 800 / 90 | 60 | DANGER | 위험 기준 도달 | EMERGENCY_WARNING |
| living_room | entrance | ON | 800 / 90 | 20 | WARNING | 현관 후보 10초 지속 | VOICE_WARNING |
| kitchen | outside | ON | 800 / 90 | 10 | DANGER | 외출 후보 10초 지속 | EMERGENCY_WARNING |
| kitchen | outside 후보 | ON | 800 / 90 | 0 | NORMAL | outside 2초 후 kitchen, 튐 무시 | NONE |
| outside | kitchen | ON | 800 / 90 | 0 | RECOVERED | DANGER 후 복귀 5초 확인 | NONE |
| kitchen | kitchen | ON | 800 / 90 | 0 | NORMAL | RECOVERED 다음 평가 | NONE |
| bedroom | bedroom | OFF | 0 / 70 | 45 | RECOVERED | WARNING 중 기기 종료 | NONE |
| kitchen | unknown | ON | 800 / 90 | 0 | NORMAL | unknown 19초, 기존 주방 유지 | NONE |
| kitchen | unknown | ON | 800 / 90 | 0 | SENSOR_UNCERTAIN | unknown 20초 지속 | CHECK_SENSOR |
| kitchen | unknown | ON | 2000 / 210 | 0 | WARNING | 센싱 불확실과 고출력 | VOICE_WARNING |
| bedroom | bedroom | ON | 2000 / 150, +2°C/s | 40 | DANGER | 경고 시간과 높은 출력·상승 | EMERGENCY_WARNING |
| living_room | living_room | ON | 2000 / 150, +2°C/s | 20 | WARNING | 주의 시간과 높은 출력·상승 | VOICE_WARNING |
| kitchen | kitchen | OFF+연기 | 0 / 100 | 0 | DANGER | 긴급 신호 우선 | EMERGENCY_WARNING |
| kitchen | kitchen | ON | 800 / 150, +10°C/s | 0 | DANGER | 급격한 온도 상승 | EMERGENCY_WARNING |
| kitchen | 미감지 | ON | 800 / 90 | 0 | SENSOR_UNCERTAIN | observation_valid=False인 미감지, 외출 근거 없음 | CHECK_SENSOR |
| kitchen | outside 저신뢰 | ON | 800 / 90 | 0 | SENSOR_UNCERTAIN | 낮은 confidence 20초, 외출 확정 안 함 | CHECK_SENSOR |
| kitchen | kitchen | 업데이트 없음 | 마지막 800 / 90 | 0 | SENSOR_UNCERTAIN | 기기 데이터 20초 경과 | CHECK_SENSOR |

## 12. 의사 코드 및 실행

```text
센싱 업데이트:
    시각과 입력 검증
    unknown/저신뢰이면 불확실 시작 시각 기록
    그 외 위치 후보의 지속 시간을 확인
    확인된 위치와 주방 이탈 시작 시각 갱신
    현재 시각으로 평가
기기 업데이트:
    시각과 입력 검증
    연속 관측의 출력/온도 변화율 갱신
    동작 시작/종료 기록
    현재 시각으로 평가
주기적 tick:
    입력의 유효 기간과 이탈 경과 시간 계산
    긴급 신호 → 기기 종료 → 외출/장기 이탈 → 불확실성 순서로 확인
    위치 및 config의 시간·출력·온도 기준으로 상태 결정
    불확실성만으로 기존 경고/위험을 해제하지 않음
    경고/위험 해제 시 RECOVERED 출력
    이전/현재 상태 저장 후 결과 반환
호출자:
    판단 결과 저장
    알림이 필요할 때 기존 AlertService.handle(결과.to_risk_decision()) 호출
```

```powershell
python -m unittest discover -s tests -v
python test_realtime.py
python test_realtime.py --input events.jsonl
python test_realtime.py --tts pyttsx3
```

예제 실행기는 상태가 바뀔 때만 LLM/TTS를 호출한다. 반복 알림 주기 정책은 포함하지 않는다. 기본 LLM은 none, TTS는 dry-run이다. 기존 Gemini 설정을 갖춘 환경에서는 `--llm gemini`를 사용할 수 있다. `output/realtime/decisions.jsonl`에 모든 판단을, `alert_output.json`에 마지막 상태 전이의 알림을 기록한다. WAV는 알림이 생성된 경우에 남는다. 실행할 때 로그/마지막 JSON은 덮어쓴다.

JSONL 예시(각 줄이 이벤트 하나):

```jsonl
{"type":"appliance","timestamp":0,"power_on":true,"power_watts":800,"temperature_c":90}
{"type":"sensing","timestamp":0,"location":"kitchen","confidence":0.95}
{"type":"sensing","timestamp":5,"location":"kitchen","confidence":0.95}
{"type":"sensing","timestamp":10,"location":"outside","confidence":0.95}
{"type":"appliance","timestamp":15,"power_on":true,"power_watts":800,"temperature_c":90}
{"type":"sensing","timestamp":20,"location":"outside","confidence":0.95}
{"type":"tick","timestamp":40}
```
