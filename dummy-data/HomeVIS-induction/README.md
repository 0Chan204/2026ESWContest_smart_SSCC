# HomeVIS 인덕션 더미 (ESP-IDF)

부엌 `induction-01`의 `burner-1`을 시뮬레이션합니다.
ESP-IDF monitor에서 1/2/3 시나리오를 선택하고 MQTT로 상태·명령·ACK를 주고받습니다.
온도와 가동 시간은 더미 데이터이며 실제 인덕션이나 GPIO를 구동하지 않습니다.

## 설정 및 실행

이 PC의 ESP-IDF 5.5.4 경로는 `/home/wonyj/.espressif/v5.5.4/esp-idf`입니다.
기존 프로젝트의 타깃은 ESP32-S3입니다.

```bash
. /home/wonyj/.espressif/tools/activate_idf_v5.5.4.sh
cd /home/wonyj/Desktop/2026ESWC/HomeVIS-EM.devices/HomeVIS-induction
idf.py menuconfig
idf.py build
idf.py -p /dev/ttyUSB0 flash monitor
```

연결한 보드에 맞게 포트를 변경합니다. 새 체크아웃이거나 타깃을 변경하려면
`menuconfig` 전에 `idf.py set-target esp32s3`를 실행합니다.
기본 대용량 단일 앱 파티션은 플래시 2 MiB 이상에서 사용할 수 있습니다.

`HomeVIS induction dummy configuration` 메뉴는 `main/Kconfig.projbuild`에서 정의합니다.

| 설정 | 설명 |
| --- | --- |
| Wi-Fi SSID / password | 접속할 네트워크. 초기 기본값은 공백. 비밀번호 공백은 개방형 네트워크 |
| MQTT broker / port | 기본 `192.168.0.2:1883`. 실제 브로커 주소로 변경 |
| MQTT username / password | 인증을 사용하면 입력 |
| NTP server | 기본 `pool.ntp.org`. 서버 접근이 가능해야 MQTT 시작 |
| Heating level | 콘솔 2/on 또는 level 없는 turn_on의 단계. 기본 3, 범위 1~9 |

입력한 값은 로컬 `sdkconfig`에 저장되고 Git에서 제외됩니다.
기존 `sdkconfig`의 Wi-Fi/MQTT 접속값은 유지됩니다.
MQTT는 TCP 연결입니다. 토픽과 3초 전송 주기는 프로토콜에 맞게 고정했습니다.
기존 `INDUCTION_DUMMY_CYCLE`, `INDUCTION_MQTT_TOPIC`, `INDUCTION_PUBLISH_INTERVAL_SEC` 설정은 더 이상 사용하지 않습니다.

UART 콘솔이 기본입니다. 보드에서 USB를 사용하면
`Component config → ESP System Settings → Channel for console output`에서
USB CDC 또는 USB Serial/JTAG를 **주 콘솔**로 선택하세요. 보조 콘솔은 입력을 받지 못합니다.

## 사용자 입력

`idf.py monitor`의 `induction-01>` 프롬프트에서 입력하고 Enter를 누릅니다.

부팅 시 선택 메뉴가 표시됩니다. 숫자 하나를 입력하면 바로 상태가 바뀝니다.

| 입력 | 상태 | 온도 | 알람 |
| --- | --- | --- | --- |
| `1` | 기본 꺼짐 (`off`), 단계 0, activeSec 0 | 25℃ | off |
| `2` | 켜짐 (`on`), 설정한 기본 단계 | 100~120℃에서 랜덤 증감 | off |
| `3` | 과열 (`overheated`), 단계 0 | 150~180℃에서 랜덤 증감 | on |

```text
induction-01> 2
induction-01> status
induction-01> 3
induction-01> 1
```

선택한 시나리오는 다음 선택 또는 서버 제어까지 유지합니다. `2`와 `3`의 온도는
선택 직후와 이후 3초마다 최대 ±3℃씩 바뀌며, 각 범위를 벗어나지 않습니다.
`1`은 냉각을 기다리지 않고 기본 꺼짐 상태로 초기화합니다.
`2`는 과열 시나리오에서도 정상 켜짐으로 전환합니다.
기존 `on`/`On`/`ON`은 `2`, `off`/`Off`/`OFF`는 `1`의 별칭입니다.
`help`로 명령 목록을 볼 수 있습니다.
`status`는 온도·단계·누적 가동 시간·알람·MQTT/NTP 준비 상태를 출력합니다.
네트워크 설정이 없거나 Wi-Fi/NTP/MQTT 연결을 기다리는 동안에도 콘솔 입력과 시뮬레이션은 동작합니다.
모니터 종료는 `Ctrl+]`입니다.

## MQTT 계약

토픽 앞부분: `home/kitchen/induction/induction-01/`

| 토픽 | 방향 | 동작 |
| --- | --- | --- |
| `state` | 기기 → 서버 | 연결·재연결 시, 제어 적용 및 동작 상태 변경 시, 마지막 발행으로부터 3초마다 |
| `command` | 서버 → 기기 | `turn_on`, `turn_off`, `set_level`. QoS 1 구독 |
| `ack` | 기기 → 서버 | 서버 명령 처리 직후. QoS 1 |

state는 QoS 0, 모든 발행은 retain false입니다. 온도와 activeSec는 주기 발행에 담고,
전원·단계·과열·냉각 완료 변경은 즉시 발행합니다. 단절 중에는 로컬 상태를 유지하며 재연결 시 최신 상태를 보냅니다.
전송 큐는 16 KiB로 제한됩니다. 모든 시각은 SNTP 기반 `YYYY-MM-DDTHH:MM:SS+09:00`이며,
유효한 시각을 얻기 전에는 MQTT를 시작하지 않습니다.

초기 상태는 `off`, 단계 0, 25℃, activeSec 0, alarm off, lastControl.publisher user입니다.
콘솔 조작은 `publisher: "user"`, 서버 제어는 `publisher: "api"`와 받은 `commandId`,
과열 시나리오 `3`은 안전 차단을 모사해 `publisher: "system"`을 기록합니다. 콘솔 조작은 state를 보내고 ACK를 만들지 않습니다.

```json
{"reportedAt":"2026-10-17T18:30:00+09:00","burners":[{"burnerId":"burner-1","deviceState":"on","level":3,"temperature":110,"activeSec":120}],"lastControl":{"publisher":"api","commandId":"cmd-20261017-d25f5e9d"},"alarm":"off"}
```

서버 명령:

```json
{"commandId":"cmd-20261017-d25f5e9d","issuedAt":"2026-10-17T18:30:00+09:00","burnerId":"burner-1","type":"set_level","level":3}
```

- `turn_on`: level 선택. 생략하면 설정된 기본 단계로 켭니다.
- `turn_off`: level 없이 가열을 중단하고 냉각합니다. 과열 시나리오도 종료하며 알람은 60℃ 이하에서 해제합니다.
- `set_level`: 정수 level 1~9 필수. 꺼져 있으면 해당 단계로 켭니다.
- 서버 turn_on/set_level도 온도는 100~120℃ 범위를 사용합니다. 단계 1~9는 출력 필드에 반영하며 자동 과열은 발생하지 않습니다.
- 이미 켜진 상태의 turn_on/set_level은 activeSec를 초기화하지 않습니다. 새로 켜질 때만 0으로 초기화합니다.
- `activeSec`는 켜진 동안 단조 시계로 누적하며, 꺼짐·냉각·과열 중에는 마지막 값을 유지합니다.

ACK는 받은 commandId를 JSON 문자열 값 그대로 돌려주며 처리 후 한 구의 상태를 `burnerState`에 담습니다.

```json
{"commandId":"cmd-20261017-d25f5e9d","result":"applied","appliedAt":"2026-10-17T18:30:01+09:00","burnerState":{"burnerId":"burner-1","deviceState":"on","level":3,"temperature":110,"activeSec":0}}
```

잘못된 구 ID·타입·단계 또는 과열 중 켜기에는 `result: "rejected"`와 `reason`을 보냅니다.
처리 큐가 가득 차면 `result: "failed"`, `reason: "busy"`를 보냅니다.
잘못된 JSON이나 유효한 commandId가 없는 요청은 ACK를 만들 수 없어 로그만 남깁니다.
명령 최대 크기는 1024바이트, commandId는 비어 있지 않은 최대 127바이트 문자열입니다.
issuedAt은 비어 있지 않은 문자열이어야 하며 예약 실행이나 만료 판단에 사용하지 않습니다.
Retained 명령은 무시합니다. 분할 수신 메시지는 합친 후 파싱합니다.
최근 성공한 서버 명령 8개의 ID와 ACK를 RAM에 보관하고, 중복 전달 시 기존 ACK를 재전송합니다.
재부팅하거나 캐시에서 밀려난 ID는 중복 검출 대상이 아닙니다. 새 제어에는 새 ID를 사용하세요.

## 더미 온도·과열 시나리오

상온은 25℃입니다. 정상 켜짐은 처음 110℃에서 시작하고, 과열은 처음 165℃에서 시작합니다.
선택 직후와 매 3초마다 ESP-IDF `esp_random()`으로 ±3℃ 이내의 변화를 생성합니다.
정상 켜짐은 100~120℃, 과열은 150~180℃로 제한하며 온도는 소수 첫째 자리까지 전송합니다.
과열 시나리오는 자동 냉각하거나 재가열하지 않고 유지합니다.

서버 turn_on/set_level은 과열 알람이 켜진 동안 거부합니다.
서버 turn_off는 cooling으로 전환하며 초당 2℃씩 냉각하고, 60℃ 이하에서 알람을 해제하고,
25℃에서 off가 됩니다. 콘솔 1/2/3은 테스트 시나리오를 즉시 전환하므로 냉각 대기 없이 선택할 수 있습니다.

## 브로커 테스트 예시

Mosquitto CLI를 설치한 PC에서 실행합니다. 인증이 필요하면 `-u`, `-P`를 추가합니다.

```bash
mosquitto_sub -h 192.168.0.2 -p 1883 -t 'home/kitchen/induction/induction-01/#' -v
mosquitto_pub -h 192.168.0.2 -p 1883 -q 1 \
  -t home/kitchen/induction/induction-01/command \
  -m '{"commandId":"test-on-001","issuedAt":"2026-10-17T18:30:00+09:00","burnerId":"burner-1","type":"turn_on","level":3}'
mosquitto_pub -h 192.168.0.2 -p 1883 -q 1 \
  -t home/kitchen/induction/induction-01/command \
  -m '{"commandId":"test-level-002","issuedAt":"2026-10-17T18:30:10+09:00","burnerId":"burner-1","type":"set_level","level":9}'
mosquitto_pub -h 192.168.0.2 -p 1883 -q 1 \
  -t home/kitchen/induction/induction-01/command \
  -m '{"commandId":"test-off-003","issuedAt":"2026-10-17T18:30:20+09:00","burnerId":"burner-1","type":"turn_off"}'
```

과열 시험은 ESP-IDF 콘솔에서 `3`을 입력합니다. 단계 9 명령만으로 자동 과열되지는 않습니다. 명령에 retain 옵션(`-r`)을 사용하지 않습니다.

## 보드 없는 호스트 테스트

ESP-IDF 활성화 후 실행합니다. 호스트 C 컴파일러와 ESP-IDF의 cJSON을 사용합니다.

```bash
bash tests/run_host_tests.sh
```

명령 검증, 숫자·On/Off 선택, 온도 범위와 양방향 증감, 시나리오 유지·전환, 냉각·과열 잠금, 타이머, lastControl, ACK/JSON, 한국 시간 변환을
AddressSanitizer/UndefinedBehaviorSanitizer로 검사합니다.
ptrace 환경에서 LeakSanitizer가 실행되지 않으면 `ASAN_OPTIONS=detect_leaks=0 bash tests/run_host_tests.sh`를 사용합니다.
실제 Wi-Fi, 콘솔 입출력, MQTT 송수신은 보드와 브로커를 연결해 확인해야 합니다.
