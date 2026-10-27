# HomeVIS 전등 더미 (ESP-IDF)

ESP-IDF 콘솔에서 On/Off를 입력받고 MQTT로 상태를 전송하며 ESP32-S3의 내장 LED를 제어합니다.
콘솔 입력과 MQTT 명령 모두 같은 LED와 상태를 변경합니다. 기본 타깃은 `esp32s3`입니다.

## 설정 및 실행

ESP-IDF 5.5.4 설치 경로: `/home/wonyj/.espressif/v5.5.4/esp-idf`.
이 PC는 EIM 설치 환경이므로 일반 터미널에서는 다음과 같이 활성화합니다.
ESP-IDF 확장이 활성화한 터미널에서는 바로 `idf.py`를 사용해도 됩니다.

```bash
. /home/wonyj/.espressif/tools/activate_idf_v5.5.4.sh
cd /home/wonyj/Desktop/2026ESWC/HomeVIS-EM.devices/HomeVIS-light
idf.py menuconfig
idf.py build
idf.py -p /dev/ttyUSB0 flash monitor
```

포트는 연결한 보드에 맞게 변경합니다. 기존 빌드가 `esp32` 타깃이면 먼저
`idf.py set-target esp32s3`를 실행한 후 `menuconfig`를 실행합니다.

`HomeVIS light dummy configuration` 메뉴는 `main/Kconfig.projbuild`에서 정의합니다.

| 설정 | 설명 |
| --- | --- |
| Light location | Room 또는 Toilet 선택. 기기 ID와 세 토픽을 함께 결정 |
| Wi-Fi SSID / password | 필수 입력. 비밀번호 공백은 개방형 네트워크 |
| MQTT broker / port | 기본 `192.168.0.2:1883`. 실제 브로커 주소 입력 |
| MQTT username / password | 인증을 사용하면 입력 |
| NTP server | 기본 `pool.ntp.org`. 타임스탬프 동기화에 사용 |
| Start with the dummy light on | 초기 전원. 기본 Off |
| On-board LED type | 기본 WS2812 RGB. 일반 단색 LED는 Single-color GPIO LED 선택 |
| On-board LED GPIO | 기본 48. DevKitC-1 v1.1은 38로 변경 |
| RGB LED white brightness | On일 때 흰색 밝기. 기본 16/255 |
| GPIO LED turns on at a low level | 단색 GPIO LED의 Active-low 설정 |

입력한 값은 로컬 `sdkconfig`에 저장되며 Git에서 제외됩니다.
MQTT 연결은 TCP입니다. 방과 화장실은 각각 해당 설정으로 빌드·플래시합니다.

내장 RGB LED는 WS2812 신호를 ESP-IDF RMT 드라이버로 전송합니다. 추가 컴포넌트 다운로드는 필요 없습니다.
On이면 흰색으로 켜지고 Off이면 꺼집니다. blink 동안 500 ms마다 실제 LED가 켜지고 꺼지며,
지정 시간이 끝나면 이전 전원 상태로 복구합니다. LED 제어는 Wi-Fi/MQTT/NTP 연결 전에도 동작합니다.
LED 출력이 완료된 후 명령 ACK를 생성합니다.

[Espressif 보드 안내](https://docs.espressif.com/projects/esp-dev-kits/en/latest/esp32s3/esp32-s3-devkitc-1/user_guide_v1.1.html)에
따르면 DevKitC-1 초기 버전은 GPIO48, v1.1은 GPIO38을 사용합니다. 다른 S3 보드는 회로도에 맞게
핀과 LED 종류를 선택합니다. 전원 표시 전용 LED는 소프트웨어 제어 대상이 아닙니다.

모니터의 `light-01>` 또는 `light-00>` 프롬프트에서 입력합니다.

```text
on
off
status
help
```

`On`, `Off`, `ON`, `OFF`도 지원합니다. Enter로 전송합니다.
UART가 기본이며, USB 콘솔 보드에서는 `Component config → ESP System Settings → Channel for console output`에서
USB CDC 또는 USB Serial/JTAG를 **주 콘솔**로 선택합니다. 보조 콘솔은 입력을 받지 못합니다.
모니터 종료는 `Ctrl+]`입니다.

## MQTT 동작

| 위치 | 기기 ID | 토픽 앞부분 |
| --- | --- | --- |
| 방 (기본) | `light-01` | `home/room/light/light-01/` |
| 화장실 | `light-00` | `home/toilet/light/light-00/` |

- `state`: 연결·재연결 시, 상태 변경 시, 마지막 전송으로부터 5초마다 전송합니다. QoS 0, retain false.
- `command`: QoS 1로 구독합니다. `deviceId`는 선택한 위치의 기기와 일치해야 합니다.
- `ack`: 처리 직후 QoS 1, retain false로 전송합니다. `state`는 처리 직후의 스냅샷입니다.
- 모든 시각은 SNTP 기반 `YYYY-MM-DDTHH:MM:SS+09:00`입니다. NTP 동기화 전에는 MQTT를 시작하지 않으며 콘솔 입력은 계속 가능합니다.
- Wi-Fi/MQTT가 끊어져도 로컬 상태와 깜빡임 타이머는 유지합니다. 재연결 시 최신 상태를 보냅니다. 전송 큐는 16 KiB로 제한됩니다.

초기 상태는 `off`/`steady`이며 첫 제어 전까지 `lastControl`은 생략합니다.
서버 제어는 `publisher: "api"`, 콘솔 제어는 `publisher: "console"`과 자동 생성한 `local-...` 명령 ID를 기록합니다.
콘솔 입력은 `state`만 전송하고 서버 명령에 대한 `ack`는 만들지 않습니다.

```json
{"reportedAt":"2026-10-17T23:00:00+09:00","power":"on","mode":"steady","lastControl":{"publisher":"api","commandId":"cmd-20261017-1a2b3c4d"}}
```

명령 예시 (방):

```json
{"commandId":"cmd-20261017-1a2b3c4d","issuedAt":"2026-10-17T23:00:00+09:00","deviceId":"light-01","type":"blink","durationSec":10}
```

`type`은 `on`, `off`, `blink`입니다. `issuedAt`은 비어 있지 않은 문자열이어야 하며 실행 예약이나 만료 판단에는 사용하지 않습니다.
`blink`의 `durationSec`은 1~86400의 정수입니다. 500 ms마다 `power`를 On/Off로 바꾸고,
그동안 `mode`는 `blink`입니다. 각 전원 변화도 `state`로 전송합니다.
시간이 끝나면 시작 전 전원과 `steady` 모드로 복귀합니다.
깜빡임 중 새 On/Off 명령은 깜빡임을 취소하고 즉시 적용합니다.
새 blink 명령은 원래 복귀 전원을 유지하면서 기간을 다시 시작합니다.

```json
{"commandId":"cmd-20261017-1a2b3c4d","result":"applied","appliedAt":"2026-10-17T23:00:01+09:00","state":{"reportedAt":"2026-10-17T23:00:01+09:00","power":"on","mode":"blink","lastControl":{"publisher":"api","commandId":"cmd-20261017-1a2b3c4d"}}}
```

잘못된 기기 ID·명령 타입·기간 등은 상태를 변경하지 않고 `result: "rejected"`와 `reason`을 보냅니다.
유효한 `commandId`가 없는 잘못된 JSON, 1024바이트 초과 메시지, retained 명령은 로그만 남기고 무시합니다.
최근 성공한 서버 명령 8개의 ID와 ACK를 RAM에 보관하므로 중복 전달 시 상태를 다시 바꾸지 않고 기존 ACK를 재전송합니다.
재부팅하거나 캐시에서 밀려난 ID는 중복 검출 대상이 아닙니다. 새 제어에는 항상 새 `commandId`를 사용하세요.

## 브로커 확인 예시

Mosquitto CLI가 있는 PC에서 실행합니다. 인증을 사용하는 경우 `-u`, `-P`를 추가합니다.

```bash
mosquitto_sub -h 192.168.0.2 -p 1883 -t 'home/room/light/light-01/#' -v
mosquitto_pub -h 192.168.0.2 -p 1883 -q 1 \
  -t home/room/light/light-01/command \
  -m '{"commandId":"test-blink-001","issuedAt":"2026-10-17T23:00:00+09:00","deviceId":"light-01","type":"blink","durationSec":10}'
```

화장실 테스트는 토픽을 `home/toilet/light/light-00/...`, `deviceId`를 `light-00`으로 바꿉니다.
명령에 retain 옵션(`-r`)은 사용하지 않습니다.

## 호스트 테스트

ESP-IDF 활성화 후 보드 없이 상태 모델·입력 검증·JSON·한국 시간 포맷을 검사할 수 있습니다.
호스트 C 컴파일러와 AddressSanitizer/UndefinedBehaviorSanitizer를 사용합니다.

```bash
bash tests/run_host_tests.sh
```

실제 Wi-Fi 접속, 콘솔 입력, MQTT 송수신은 보드와 브로커를 연결한 후 확인해야 합니다.
