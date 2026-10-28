# 여러 Raspberry Pi / ESP32의 Wi-Fi CSI 수집

이 문서의 프로젝트 루트는 통합 저장소의 `ai-wifi-sensing/collection` 폴더입니다. `.env`도 이 폴더에 둡니다. 전체 구성과 ESP32 펌웨어는 [CSI 펌웨어 안내](../../embedded/wifi-sensing/README.md)를 참고하세요.

노트북 USB에 ESP32 네 대를 직접 연결해 수집하려면 [local/README.md](local/README.md)를 참고하세요. 프로젝트 루트에서 `.venv/bin/python -m local`로 별도의 로컬 수집 화면을 실행합니다.

노트북의 **파이썬 데스크톱 앱(Tkinter + Matplotlib)**에서 ESP32를 선택하면, 각 Raspberry Pi의 **C 에이전트**가 USB 시리얼 데이터를 병렬 수집하고 결과를 노트북으로 자동 전송합니다.

```text
노트북: Tkinter 화면 + HTTP 수집 서버 + AI_WIFI 전처리 + 통합 그래프
   ├── LAN ── pi-01: C 에이전트 ── USB ── esp-01, esp-02, ...
   └── LAN ── pi-02: C 에이전트 ── USB ── esp-01, esp-02, ...
```

- 기본 대기 **5초**, 보드별 최종 길이 **500개**입니다. 각 ESP32에서 유효 CSI **550개를 수집한 뒤 앞 25개·뒤 25개를 제외**합니다. 최종 길이는 화면에서 변경할 수 있습니다.
- 연결된 ESP32 중 원하는 대수 또는 특정 장치를 선택합니다. ID는 `Pi ID / ESP32 ID`로 구분합니다.
- 선택한 모든 Pi의 USB 준비가 끝나면 공통 시작 시각을 배포합니다. 각 보드는 자기 목표 개수를 채우면 독립적으로 멈추므로 수신 속도가 달라도 최종 길이는 같습니다.
- 수집 종료 후 별도 버튼 없이 업로드합니다. 노트북 화면이 자동으로 전처리하고 기본으로 ESP32별 개별 그래프를 표시합니다. 통합 비교 화면도 선택할 수 있습니다.
- C 에이전트는 ESP32별 읽기 스레드와 디스크 버퍼를 사용합니다. 과학 연산은 노트북에서 수행합니다.
- 업로드 실패 시 Pi의 원본을 유지하고 3초 간격으로 다시 시도합니다. 완료된 수집의 `result.json`은 에이전트 재시작 후에도 재전송됩니다.

## 1. 노트북 실행

Python 3.10 이상을 사용합니다. Ubuntu/Debian에서 Tk가 없다면 먼저 `sudo apt install python3-tk python3-venv`를 실행합니다.

```bash
cd /path/to/2026ESWContest_smart_SSCC/ai-wifi-sensing/collection
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r local/requirements.txt
cp .env.example .env
# .env의 CSI_TOKEN을 팀의 로컬 토큰으로 변경해 주세요.
python -m csi_capture.desktop
```

앱을 실행하면 노트북에서 TCP **8765** 포트의 서버도 함께 실행됩니다. Pi와 노트북은 서로 접근 가능한 네트워크에 연결하고, 방화벽에서 Pi의 8765 접근을 허용합니다. Pi 설정에는 `0.0.0.0`이 아니라 **노트북의 LAN IP**를 넣습니다.

프로젝트 루트의 **`.env`에 고정된 `CSI_TOKEN`**을 사용합니다. 노트북 앱과 C 에이전트가 자동으로 읽으며, 재실행해도 토큰은 바뀌지 않습니다. **같은 `.env` 파일을 각 Pi의 프로젝트 루트에도 한 번 복사**하세요. Pi 설정 JSON에 토큰을 넣거나 매번 화면에서 복사할 필요가 없습니다.

```dotenv
# .env — 노트북과 모든 Pi에서 같은 값 사용
CSI_TOKEN=your-fixed-team-token
```

새 체크아웃에 `.env`가 없다면 `.env.example`을 `.env`로 한 번 복사하고 팀의 기존 토큰을 넣습니다. 토큰은 영문·숫자·`.`·`_`·`~`·`-` 1–255자를 사용하며, 작은따옴표/큰따옴표로 감싸도 됩니다. 값의 셸 확장이나 변수 치환은 하지 않습니다. `.env`는 Git에서 제외됩니다.

이미 export한 `CSI_TOKEN`이 있으면 `.env`보다 우선합니다. `.env` 값으로 돌아가려면 `unset CSI_TOKEN` 후 실행하세요. 다른 파일을 쓰려면 `CSI_ENV_FILE=/절대/경로/파일`로 지정할 수 있습니다. `.env`와 환경변수 모두에 토큰이 없으면 노트북 앱은 설정 오류를 표시합니다. 자동 생성하지 않습니다.

노트북의 기본 `.env`는 실행 디렉터리와 관계없이 프로젝트 루트에서 찾습니다. Pi도 `pi_agent/csi-agent`의 상위 프로젝트 루트에서 찾습니다. 서버 재시작 후 자동 재전송하려면 같은 토큰과 같은 데이터 폴더를 유지하세요.

서버 통신은 기본 HTTP이며 신뢰할 수 있는 LAN용입니다. 인터넷에 직접 공개하는 구성이 아닙니다.

## 2. Raspberry Pi 빌드와 실행

이 폴더의 **`pi_agent`, `configs`, `.env`**를 Pi로 복사합니다. `.env`는 숨김 파일이므로 복사에서 빠뜨리지 마세요. Pi의 프로젝트가 `~/2026ESWContest_smart_SSCC/ai-wifi-sensing/collection`라면 `~/2026ESWContest_smart_SSCC/ai-wifi-sensing/collection/.env`에 둡니다. Pi에는 Python이나 NumPy가 필요하지 않습니다. 바이너리는 저장소에 포함하지 않으므로 Pi에서 아래 명령으로 직접 빌드해 주세요. 개수 수집은 새 C 에이전트가 필요하며, 이전 에이전트가 연결되어 있으면 노트북에서 업데이트 안내를 표시합니다.

```bash
sudo apt update
sudo apt install build-essential pkg-config libcurl4-openssl-dev libjson-c-dev
make -B -C pi_agent
cp configs/pi-01.example.json configs/pi-01.local.json
ls -l /dev/ttyACM* /dev/ttyUSB*
```

`-B`는 복사된 PC용 바이너리가 있어도 Pi에서 강제로 다시 컴파일합니다. `cannot execute binary file: Exec format error`가 나오면 Pi의 프로젝트 폴더에서 `make -B -C pi_agent`를 실행한 뒤 다시 시작하세요.

`configs/pi-01.local.json`을 실제 연결에 맞게 수정합니다.

```json
{
  "server": "http://192.168.0.10:8765",
  "pi_id": "pi-01",
  "spool_dir": "spool-pi-01",
  "devices": [
    {
      "id": "esp-01",
      "port": "/dev/ttyACM0",
      "baud": 115200,
      "target_mac": ""
    },
    {
      "id": "esp-02",
      "port": "/dev/ttyACM1",
      "baud": 115200,
      "target_mac": ""
    }
  ]
}
```

- `pi_id`는 Pi마다 다르게 지정합니다. 두 번째 Pi는 `pi-02` 등으로 추가합니다.
- `devices`에 연결한 ESP32들을 등록합니다. 등록된 장치 가운데 이번 수집에 사용할 장치는 노트북에서 선택합니다.
- `port`에 `/dev/ttyACM0`, `/dev/ttyACM1`, `/dev/ttyUSB0`처럼 짧게 적으면 됩니다. 에이전트가 연결된 장치의 `/dev/serial/by-id/...` 경로를 자동으로 찾고 `configs/pi-01.local.json.ports.json`에 저장합니다. 이후 재연결이나 프로세스 재시작으로 tty 번호가 바뀌어도 저장된 보드를 사용합니다. 고정 경로를 제공하지 않는 장치는 입력한 경로를 그대로 사용합니다.
- 다른 보드로 교체하여 새로 매핑하려면 에이전트를 종료하고 해당 `.ports.json` 캐시를 삭제한 뒤 다시 실행합니다. 설정의 짧은 `port` 값을 변경하면 해당 항목도 다시 매핑합니다. 기존의 긴 `/dev/serial/by-id/...` 설정도 사용할 수 있습니다.
- `baud`는 **ESP32 펌웨어와 반드시 일치**해야 합니다. 예시 기본값은 115200이며 9600, 57600, 230400, 460800, 921600도 지원합니다. 처리량을 높이려면 펌웨어와 Pi 양쪽을 함께 변경합니다.
- `target_mac`은 측정할 송신기/AP의 MAC입니다. 비워 두면 개수 수집 시작 후 처음 받은 유효 CSI의 MAC으로 고정합니다. 다른 송신기 패킷은 목표 개수에 포함하지 않습니다. 같은 송신기를 비교하려면 모든 장치에 같은 MAC을 명시합니다.
- `spool_dir`의 상대경로는 에이전트를 실행한 작업 디렉터리 기준입니다. 부모 디렉터리는 미리 존재해야 합니다.
- 토큰 우선순위는 export한 `CSI_TOKEN` → 프로젝트 `.env` → 기존 JSON의 `token`입니다. 새 설정에는 JSON의 `token`이 필요하지 않습니다.

```bash
./pi_agent/csi-agent configs/pi-01.local.json
```

시리얼 접근 권한 오류라면 Pi 사용자를 `dialout` 그룹에 추가한 뒤 재로그인합니다. 다른 시리얼 모니터와 이 에이전트가 같은 USB 포트를 동시에 읽지 않도록 합니다.

### ESP32 펌웨어의 출력 조건

ESP32는 **이미 CSI 수신 펌웨어가 실행되고 있어야** 합니다. 이 프로젝트는 ESP32 펌웨어를 플래싱하거나 CSI를 발생시키지 않습니다. 수신 대상 Wi-Fi 패킷이 있어야 데이터가 생깁니다.

다음 두 가지 줄바꿈 CSV 형식을 읽습니다.

1. 기존 AI_WIFI `edge_node.py`의 6열 형식:

   ```text
   local_timestamp,"[허수0,실수0,허수1,실수1,...]",rssi,mac,first_word,len
   ```

2. Espressif의 기존 25열 `CSI_DATA` 형식:

   ```text
   type,id,mac,rssi,rate,sig_mode,mcs,bandwidth,smoothing,not_sounding,aggregation,stbc,fec_coding,sgi,noise_floor,ampdu_cnt,channel,secondary_channel,local_timestamp,ant,sig_len,rx_state,len,first_word,data
   ```

`local_timestamp`는 ESP32의 32비트 마이크로초 카운터이고, `data`는 최소 128개의 signed int8 값이 든 JSON 배열입니다. `len`은 배열 길이와 일치해야 합니다. 다른 칩/펌웨어의 다른 열 배치는 `csi_capture/serial_format.py`에 명시적으로 추가해야 합니다. C가 저장한 원문과 노트북의 파싱 성공/실패 개수는 결과 폴더에 남습니다.

## 3. 화면 사용

1. Pi 에이전트를 실행하고 노트북 화면에 장치가 나타나는지 확인합니다.
2. 대수를 입력하고 **대 선택**을 누르거나, Ctrl/Shift로 개별 ESP32를 선택합니다.
3. 대기 시간과 **최종 수집 길이(개)**를 지정합니다. 기본값은 **5초 / 500개**입니다. 최종 500개를 선택하면 보드마다 550개를 수집합니다.
4. **수집 시작**을 누릅니다. USB 준비 완료 후 `5 → 4 → 3 → 2 → 1` 카운트다운이 표시됩니다. 수집 중에는 장치 목록과 그래프 아래에 보드별 `현재 개수 / 550`, 큰 숫자로 `완료 보드 수 / 전체 보드 수`를 표시합니다. 빠른 보드가 먼저 멈춰도 느린 보드는 목표를 채울 때까지 계속 수집합니다.
5. 결과가 자동으로 **장치별 보기**에 표시됩니다. ESP32 두 대는 위아래 그래프로 나뉘며, 각 장치의 ID와 유효 패킷 수가 제목에 표시됩니다. 네 대까지 한 페이지에서 보며, 그보다 많으면 **이전/다음**으로 이동합니다.
6. **통합 비교**를 선택하면 모든 ESP32를 한 그래프에 겹쳐 볼 수 있습니다. 범례를 클릭해 장치를 숨기거나 다시 표시할 수 있습니다. 가로축은 **샘플 번호 1–500**입니다. 실제 수신 시각과 경과 시간도 CSV에 남습니다. 보드별 수신 속도가 다르면 같은 샘플 번호의 실제 시각은 다를 수 있습니다.

CSI를 받지 못한 장치도 개별 그래프 칸이 유지되며 `NO DATA`와 원본/파싱 성공 건수가 표시됩니다. 데이터가 없는 장치를 0인 신호로 그리지 않습니다. 장치별 한국어 수신 상태는 그래프 아래에서도 확인할 수 있습니다.

그래프 메뉴:

| 표시 방식 | 의미 |
| --- | --- |
| 변화량 RMS | 남긴 데이터 중 첫 25개 패킷의 서브캐리어별 중앙값을 빼고 RMS 계산. 기본 비교 지표 |
| 서브캐리어 진폭 | 같은 유효 서브캐리어 하나를 모든 장치에서 비교. 인덱스 0–25는 -26…-1, 26–51은 +1…+26 |
| 원본 진폭 평균 | AGC 보정 전 52개 진폭의 평균 |
| RSSI | 각 수집 패킷의 RSSI |

AGC 보정 직후 모든 서브캐리어의 평균은 약 1이므로 기본 비교 그래프로 적합하지 않습니다. RMS는 **시각화용 지표**이며 재실/호흡 판정 결과가 아닙니다. 기준을 계산하는 첫 25개에 움직임이 있으면 그 움직임도 기준에 포함됩니다.

AI_WIFI의 19개 학습 특성 추출이나 재실 분류는 이 앱에서 실행하지 않습니다.

## 4. AI_WIFI 전처리와 저장 파일

원본 `HomeVIS-AI_Wifi/src/wifi_occupancy_pipeline.py`의 수집 당시 버전을 변경 없이 `csi_capture/vendor/ai_wifi_pipeline.py`에 포함했습니다. 개수 기준 수집은 이 모듈의 진폭 파싱·Hampel 함수와 같은 AGC·Savitzky–Golay 설정을 사용합니다. **500개 길이를 유지하도록 시간 보간/25Hz 리샘플링은 적용하지 않습니다.** 이전 시간 기준 세션을 열 때는 기존 공통 시간 전처리를 사용합니다.

1. 대상 MAC 선택/필터링
2. 유효 CSI 550개 중 앞뒤 25개씩 제외하여 500개 보존
3. LLTF 64개 중 유효 서브캐리어 52개 추출, `first_word_invalid` 보정
4. 패킷별 평균으로 나누는 AGC 보정
5. Hampel: k=3, 3 sigma
6. 실제 패킷 순서와 개수 유지
7. Savitzky–Golay: 윈도우 7, 차수 3

부팅 로그, 손상된 CSI, 영벡터 CSI, 다른 MAC의 패킷은 수집 목표에 포함하지 않습니다. 제외 전 원본 550개는 보존하고, 분석과 그래프에는 중앙 500개를 사용합니다.

```text
data/<session-id>/
  session.json                     # 설정, 상태, 선택 장치, 시각, 수신 통계, SHA-256
  pi-01/esp-01.raw.csv              # 제외 전 원본 550개: Pi 수신 시각 + ESP32 원문
  pi-01/esp-01.csv                  # 앞뒤 25개씩 제외한 최종 500개, AI_WIFI 호환 7열 CSV
  pi-02/...
  processed/pi-01__esp-01.csv       # 500행: 샘플 번호, 경과시간, valid, RMS, RSSI, 52개 진폭
```

`processed`는 데스크톱에서 결과를 표시하거나 데모를 실행할 때 생성됩니다. 원본만 받은 상태에서도 나중에 **기존 결과 폴더 열기**로 전처리할 수 있습니다. **그래프 PNG 저장**으로 현재 표시를 저장합니다.

Pi에는 `spool_dir/<session-id>/`에 원본, 완료 메타데이터 `result.json`, 업로드 확인 마커 `uploaded`가 남습니다. 자동 삭제하지 않으므로 실험 후 저장 공간을 관리하세요. 수집 도중 강제 전원 차단으로 `result.json`이 작성되지 않았다면 완료 수집으로 자동 복구하지 않으며, 남은 원본을 별도로 확인해야 합니다.

## 5. 시작 시각과 오류 처리

- 대기 시간은 **모든 선택 장치의 준비 완료 시점**부터 계산합니다. 버튼 클릭부터는 USB 준비 시간이 추가됩니다.
- 0–0.5초 대기를 지정하면 명령 배포를 위해 최소 0.5초를 확보합니다. 기본 5초에는 추가되지 않습니다.
- Pi는 HTTP 왕복시간 중간값으로 노트북 시계를 추정하고, 실제 구간 제어는 `CLOCK_MONOTONIC`을 사용합니다. HTTP 지연 때문에 수집 스레드가 멈추지 않습니다.
- Pi 간 하드웨어 동기화를 보장하지 않습니다. USB 지연, 네트워크 비대칭 지연, ESP32 시계 차이가 남습니다. 정밀 동기화가 필요하면 실제 장치에서 오차 측정과 추가 동기화가 필요합니다. 왕복시간은 세션에 기록합니다.
- Pi는 수집 전부터 USB를 읽어 버퍼를 비웁니다. 펌웨어에 start/stop 명령을 보내는 방식이 아니라, 계속 출력되는 CSI 중 목표 개수를 저장합니다. 25Hz로 수신한다면 550개 수집은 약 22초 걸립니다. 실제 종료 조건은 각 보드의 개수입니다.
- 최종 길이 2–20000개, 대기 최대 3600초, Pi당 최대 64개, ESP32당 원본 최대 48 MiB입니다. 실제 연결 가능 대수/속도는 USB 허브 전력·UART 대역폭·Wi-Fi 패킷 속도에 따라 달라집니다.
- 장치 준비 30초 초과, 수집 중 유효 패킷이 10초 동안 오지 않음, 전체 수집 600초 초과는 정상 종료 대신 오류로 처리합니다. `end_at`은 개수 모드에서 오류 방지 제한 시각이며, 실제 수집 구간은 장치별 `first_host_timestamp`/`last_host_timestamp`로 확인합니다.
- 목표를 채우지 못하면 일부 누락 상태로 표시합니다. 부분 데이터에도 앞뒤 25개씩 제외하며, 남은 개수를 500개로 채워 넣지 않습니다. 늦게 도착한 결과도 수신합니다.
- 수집 취소 또는 일부 장치 오류를 전체 정상 성공으로 표시하지 않습니다. 정상 장치의 부분 원본은 보존합니다.

## 6. 하드웨어 없이 확인

C 바이너리를 현재 컴퓨터에서 빌드한 후 다음을 실행합니다. **실제 무선 측정이 아닌 합성 데이터**임이 그래프에 표시됩니다.

```bash
make -C pi_agent
python -m csi_capture.demo --output data/demo
```

이 명령은 C 에이전트 두 개(각 ESP32 두 대)를 실행하고 기본 5초 대기 후 각 보드에서 550개 수집·최종 500개 보존을 확인합니다. `data/demo/demo_result.png`와 원본/전처리 CSV를 생성합니다. `--samples 100`처럼 최종 길이를 변경할 수 있습니다.

실제 화면에서 가상 장치를 사용하려면 먼저 노트북 앱을 실행한 뒤, 같은 토큰을 넣은 Pi 설정으로 다음 명령을 실행합니다. `--simulate`에서는 실제 USB를 열지 않습니다.

```bash
./pi_agent/csi-agent configs/pi-01.local.json --simulate
```

자동 검증:

```bash
python -m pip install -r requirements-dev.txt -r local/requirements.txt
python -m pytest -q tests
# 디스플레이가 있는 환경에서 네이티브 화면까지 검사
PYTHONPATH=. python tests/ui_smoke.py
```

테스트는 다중 C 에이전트, 가상 USB(PTY)의 분할 줄 읽기, 대기/수집 경계, 취소, 장치 열기 실패, 재시작·재전송, 중복 업로드, 토큰 검증, 전처리 원본 일치, 패킷 공백 등을 확인합니다. 실제 Raspberry Pi ARM 빌드와 ESP32 보드의 CSI 품질·동시 수집 성능은 별도 하드웨어 검증이 필요합니다.

원본 문서의 2026-10-19 검증 기록: 자동 테스트 **30개 통과**. 수신 속도가 다른 가상 USB 두 대의 독립적인 개수 종료, 정확한 앞뒤 25개 제외, USB 번호 변경 후 저장된 보드 매핑 유지, 유효 CSI 미수신 오류 처리를 확인했습니다. 화면에서는 C 에이전트 2개/모의 ESP32 4개의 **5초 대기 + 보드당 550개 수집 → 최종 500개**, 개별/통합 그래프, 카운트다운과 보드별 개수 진행률을 확인했습니다. 모의 화면은 `data/ui-smoke/desktop.png`에 저장됩니다.

## 참고

- 전처리 원본 SHA-256: `ef3a40b85855774ce7b8d003808ddb8efa63038d55998334446f113a7336180c`
- [Espressif CSI CSV 형식](https://github.com/espressif/esp-csi/blob/master/examples/get-started/README.md)
- [Espressif Wi-Fi CSI 데이터와 first_word_invalid](https://docs.espressif.com/projects/esp-idf/en/v5.0/esp32/api-guides/wifi.html)
- [SciPy Savitzky–Golay API](https://docs.scipy.org/doc/scipy/reference/generated/scipy.signal.savgol_filter.html)
- [Python Tkinter 문서](https://docs.python.org/3/library/tkinter.html)

## 통합 저장소 이관

이 코드는 `HomeVIS-CSI_Collection/collector`에서 이관했습니다. 원본의 실제 `.env`·로컬 JSON·USB 장치 매핑·수집 데이터·재전송 대기열·실행 바이너리·캐시를 제외했습니다. 수집 서버와 Pi의 토큰은 새 환경에서 직접 설정해 주세요.

공개 Pi 설정의 `192.168.0.10:8765`는 예시 주소입니다. 실제 노트북 주소로 변경하고 Pi마다 고유한 `pi_id`를 지정해 주세요. Python은 이 `collection/` 폴더를 기준으로 `.env`를 찾으며, C 에이전트는 실행 파일의 상위 폴더인 `collection/`에서 찾습니다. 폴더를 분리 복사하실 때도 `pi_agent/`와 `.env`의 상대 배치를 유지해 주세요.

의존성 설치와 테스트는 위 안내를 사용하고, 변경 단위별 커밋 제목·본문은 [COMMIT_GUIDE.md](COMMIT_GUIDE.md)를 참고해 주세요.

### 이관 검증 결과 · 2026-10-28

- `/tmp`의 별도 복사본에서 Pi C 에이전트를 현재 PC용으로 컴파일하고 기존 자동 테스트 **43개**를 모두 통과했습니다.
- 가상 USB 4대의 로컬 수집 GUI와 C 에이전트 2개·모의 수신기 4대의 분산 수집 GUI 검증을 통과했습니다. 5초 대기, 각 550개 수집 → 500개 보존, 행동 라벨, 보드별 진행률과 개별/통합 그래프를 확인했습니다.
- AP·수신기 두 펌웨어를 ESP-IDF 5.5.4에서 공개 설정으로 빌드했습니다. 공개 비밀번호 기본값은 공백이며 실제 실행에는 로컬 설정이 필요합니다.
- 원본 로컬 비밀번호·CSI_TOKEN 미포함, Python/C 수집 로직의 원본 일치, 새 문서의 로컬 링크와 Git 제외 규칙을 확인했습니다.
- 실제 Pi ARM 빌드·ESP32 업로드·무선 CSI 측정은 수행하지 않았습니다. 이번 화면 검증은 합성 데이터와 가상 USB를 사용했습니다.
