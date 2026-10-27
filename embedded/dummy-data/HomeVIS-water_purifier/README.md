# HomeVIS 정수기 더미 (ESP-IDF)

부엌의 `water-01`을 시뮬레이션합니다. ESP-IDF 모니터에서 On/Off를 입력하고,
MQTT `dispense` 명령으로 지정 용량을 가상 출수합니다. 실제 펌프나 GPIO는 구동하지 않습니다.

## 설정 및 실행

이 PC의 ESP-IDF는 `/home/wonyj/.espressif/v5.5.4/esp-idf`에 있습니다.
일반 터미널에서는 EIM 활성화 스크립트를 먼저 실행합니다.
ESP-IDF 확장이 활성화한 터미널에서는 바로 `idf.py`를 사용해도 됩니다.

```bash
. /home/wonyj/.espressif/tools/activate_idf_v5.5.4.sh
cd /home/wonyj/Desktop/2026ESWC/HomeVIS-EM.devices/HomeVIS-water_purifier
idf.py set-target esp32
idf.py menuconfig
idf.py build
idf.py -p /dev/ttyUSB0 flash monitor
```

`esp32`는 기존 `.vscode/settings.json`에 지정된 타깃입니다. 실제 보드가 ESP32-C6나
ESP32-S3이면 각각 `esp32c6`, `esp32s3`로 바꿉니다. `set-target`은 최초 설정 또는
보드 변경 시 실행하며 기존 `sdkconfig`를 초기화하므로 이후 네트워크 설정을 입력합니다.
포트도 연결한 보드에 맞춰 바꿉니다. 모니터 종료는 `Ctrl+]`입니다.

`menuconfig → HomeVIS water purifier dummy configuration`에서 설정합니다.
설정 항목은 `main/Kconfig.projbuild`에서 정의합니다.

| 항목 | 기본값 / 설명 |
| --- | --- |
| Wi-Fi SSID / password | 공백. 실제 네트워크 정보 입력. 비밀번호 공백은 개방형 Wi-Fi |
| MQTT broker hostname / port | `192.168.0.2:1883`. 실제 브로커 주소로 변경 |
| MQTT username / password | 공백. 인증이 있으면 입력 |
| NTP server | `pool.ntp.org` |
| Default dispense amount for console on | 250 mL, 1~5000 |
| Simulated dispensing speed | 50 mL/s, 1~1000 |

MQTT 연결은 TCP입니다. 네트워크 정보는 로컬 `sdkconfig`에 저장되며 Git에서 제외됩니다.
`sdkconfig.defaults`는 최소 2 MiB 플래시에 맞는 ESP-IDF의 큰 단일 앱 파티션을 선택합니다.
기존 sdkconfig를 유지할 경우 `Partition Table → Single factory app (large)`를 선택합니다.

UART 콘솔이 기본입니다. USB 콘솔 보드에서는 `Component config → ESP System Settings →
Channel for console output`에서 USB CDC 또는 USB Serial/JTAG를 주 콘솔로 선택합니다.

## 사용자 입력

`water-01>` 프롬프트에서 입력하고 Enter를 누릅니다.

```text
on
status
off
help
```

- `on`, `On`, `ON`: 설정된 기본 용량의 출수를 시작합니다. 기본 250 mL는 5초 후 자동 완료됩니다.
- `off`, `Off`, `OFF`: 출수를 즉시 중지하고 그때까지의 가상 출수량을 정수 mL로 기록합니다.
- `status`: 현재 상태, 마지막 출수량, MQTT·시각 동기화 여부를 로그로 확인합니다. 출수량 `-1`은 아직 기록이 없음을 의미합니다.
- 출수 중 다시 On을 입력하거나 새로운 MQTT 출수 명령을 보내면 `busy`로 거절합니다.

On/Off는 출수 시작/정지입니다. MQTT 상태에는 지정된 `idle`/`dispensing`만 사용합니다.
부팅 시 `idle`, `lastDispensedMl: null`이며 첫 제어 전에는 `lastControl`을 생략합니다.
콘솔 제어는 `publisher: "console"`과 자동 생성된 `local-...` ID를 기록합니다.
콘솔 제어는 `state`로 알리고 서버 명령용 `ack`는 생성하지 않습니다.
네트워크 미설정·연결 끊김·NTP 대기 중에도 콘솔 입력과 출수 시뮬레이션은 동작합니다.

## MQTT 규격

토픽 앞부분은 `home/kitchen/water_purifier/water-01/`입니다.

| 토픽 | 방향 | 동작 |
| --- | --- | --- |
| `state` | 기기 → 서버 | 5초마다, 상태 변경 시, 연결·재연결 시. QoS 0, retain false |
| `command` | 서버 → 기기 | QoS 1 구독. `dispense` 명령 처리 |
| `ack` | 기기 → 서버 | 처리 직후의 상태 스냅샷. QoS 1, retain false |

시각은 SNTP 동기화 후 `YYYY-MM-DDTHH:MM:SS+09:00`으로 생성합니다.
유효한 시각을 위해 최초 NTP 동기화 후 MQTT를 시작합니다.
출수 진행·완료 시간 계산에는 네트워크나 시각 보정의 영향을 받지 않는 단조 시계를 사용합니다.
오프라인 중의 과거 상태는 저장하지 않으며 재연결 시 최신 상태를 전송합니다.

서버 명령 예시:

```json
{"commandId":"cmd-20261017-5e6f7a8b","issuedAt":"2026-10-17T07:30:00+09:00","deviceId":"water-01","type":"dispense","amountMl":250}
```

`amountMl`은 1~5000 정수입니다. `issuedAt`은 비어 있지 않은 문자열로 검증하며
예약 실행·만료 판단에는 사용하지 않습니다. 명령을 수락하면 즉시 출수를 시작하고 다음처럼 ACK를 보냅니다.

```json
{"commandId":"cmd-20261017-5e6f7a8b","result":"applied","appliedAt":"2026-10-17T07:30:01+09:00","state":{"reportedAt":"2026-10-17T07:30:01+09:00","status":"dispensing","lastDispensedMl":null,"lastControl":{"publisher":"api","commandId":"cmd-20261017-5e6f7a8b"}}}
```

완료 후에는 `idle`과 완료 용량을 `state`로 전송합니다. `applied`는 출수 시작 수락을 뜻하며
완료 ACK는 별도로 생성하지 않습니다.

```json
{"reportedAt":"2026-10-17T07:30:06+09:00","status":"idle","lastDispensedMl":250,"lastControl":{"publisher":"api","commandId":"cmd-20261017-5e6f7a8b"}}
```

잘못된 기기 ID·타입·용량 또는 출수 중 새 명령은 상태를 변경하지 않고
`result: "rejected"`, `reason`과 현재 상태를 ACK에 담습니다.
유효한 `commandId`가 없는 메시지, 깨진 JSON, 1024바이트 초과 메시지,
retained 명령은 로그만 남기고 무시합니다. MQTT 메시지가 여러 조각으로 와도 합쳐 처리합니다.
요청 큐가 가득 차면 `reason: "busy"`로 응답하며 이 경우 상태 스냅샷은 생략합니다.

최근 성공한 서버 명령 8개의 ID와 ACK를 RAM에 보관합니다. 중복 전달 시 기존 ACK만 다시 보내고
물을 다시 출수하지 않습니다. 재부팅하거나 캐시에서 밀려난 ID는 중복 검출 대상이 아닙니다.
새 출수에는 항상 새로운 `commandId`를 사용합니다. MQTT 전송 큐는 16 KiB로 제한됩니다.

## 브로커 테스트

Mosquitto CLI를 사용할 수 있는 PC에서 실행합니다. 인증이 있다면 `-u`, `-P`를 추가합니다.
명령 토픽에는 retain 옵션(`-r`)을 사용하지 않습니다.

```bash
mosquitto_sub -h 192.168.0.2 -p 1883 -t 'home/kitchen/water_purifier/water-01/#' -v
mosquitto_pub -h 192.168.0.2 -p 1883 -q 1 \
  -t home/kitchen/water_purifier/water-01/command \
  -m '{"commandId":"test-water-001","issuedAt":"2026-10-17T07:30:00+09:00","deviceId":"water-01","type":"dispense","amountMl":250}'
```

`dispensing` 상태와 ACK, 약 5초 후 `idle` 및 `lastDispensedMl: 250`을 확인합니다.
같은 `commandId`를 다시 보내면 ACK만 재전송됩니다. 출수 중 `off`를 입력하면 중간 용량으로 종료됩니다.

## 보드 없는 테스트

ESP-IDF 활성화 후 실행합니다. 호스트 C 컴파일러와 AddressSanitizer/UndefinedBehaviorSanitizer로
입력 검증, 출수 시간·용량, 중도 정지, busy 거절, JSON 필드 및 한국 시간 포맷을 확인합니다.

```bash
bash tests/run_host_tests.sh
```

ptrace를 사용하는 실행 환경에서 LeakSanitizer 오류가 나면 `ASAN_OPTIONS=detect_leaks=0`을
앞에 붙여 실행할 수 있습니다. 실제 Wi-Fi 접속, MQTT 송수신, UART/USB 콘솔은 보드와 브로커에서 확인합니다.
