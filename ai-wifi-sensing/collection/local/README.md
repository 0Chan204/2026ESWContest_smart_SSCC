# 노트북 USB 직결 CSI 수집

명령은 통합 저장소의 `ai-wifi-sensing/collection` 폴더에서 실행합니다. 전체 장치 구성은 [CSI 펌웨어 안내](../../../embedded/wifi-sensing/README.md)를 참고하세요.

ESP32 네 대를 노트북 USB에 연결해 파이썬 데스크톱 앱에서 직접 수집합니다. Raspberry Pi와 네트워크 서버 없이 실행하며, 기존 프로젝트의 CSI 파싱·전처리·그래프 코드를 공통으로 사용합니다. `local` 폴더는 `csi_capture` 폴더와 함께 이 프로젝트 안에서 사용합니다.

## 실행

노트북 터미널에서 최초 한 번 의존성을 설치합니다.

```bash
cd /path/to/2026ESWContest_smart_SSCC/ai-wifi-sensing/collection
.venv/bin/python -m pip install -r local/requirements.txt
```

ESP32 네 대를 연결하고 실행합니다.

```bash
.venv/bin/python -m local
```

또는 `.venv/bin/python local/run.py`로도 실행할 수 있습니다. `local` 폴더 안에서 실행한다면 `../.venv/bin/python run.py`를 사용합니다. 새 환경에서는 프로젝트 루트에서 `python3 -m venv .venv`로 가상환경을 먼저 만들고 위 설치 명령을 실행하세요. Ubuntu/Debian에서 Tk가 없으면 `sudo apt install python3-tk`가 필요합니다.

## 기본 동작

1. USB 시리얼 장치를 자동 검색합니다. 네 대가 연결되면 기본으로 `esp-01`부터 `esp-04`까지 선택됩니다. 일부만 연결된 경우 화면에서 수집할 장치를 직접 선택할 수 있습니다.
2. **행동 선택**에서 `fall`, `lie_down`, `get_up`, `none` 중 하나를 클릭한 뒤 **수집 시작**을 누릅니다. 기본 선택은 `none`이며, 수집 중에는 선택을 변경할 수 없습니다. 다음 수집에도 마지막 선택이 유지됩니다.
3. 모든 선택 USB가 열리면 기본 **5초 대기** 카운트다운을 시작합니다. 대기 중에는 USB를 계속 읽고 버퍼를 비웁니다.
4. ESP32마다 유효 CSI **550개**를 독립적으로 수집합니다. 보드별 진행률은 `현재 개수 / 550`으로 표시하며, 목표를 채운 보드부터 멈춥니다.
5. 앞 **25개**, 뒤 **25개**를 제외해 최종 **500개**를 저장합니다. 화면의 최종 수집 길이를 N으로 바꾸면 보드당 N+50개를 받습니다.
6. AGC·Hampel·Savitzky–Golay 전처리 후 장치별 그래프가 자동으로 표시됩니다. 통합 비교 화면도 사용할 수 있습니다. 그래프 가로축은 샘플 번호입니다.

창 높이가 작으면 왼쪽 설정 영역의 스크롤바를 내려 기존 결과 열기·PNG 저장 버튼을 사용할 수 있습니다.

ESP32에는 기존과 동일하게 CSI를 USB CSV로 출력하는 펌웨어가 실행 중이어야 합니다. 부팅 로그·손상된 데이터·영벡터 CSI·다른 송신기 MAC의 패킷은 목표 개수에서 제외합니다. 송신기 MAC을 지정하지 않으면 각 보드가 처음 받은 유효 CSI의 MAC으로 고정합니다. 그래프에는 보드마다 500개가 표시되며, 보드별 수신 속도에 따라 실제 수집 종료 시각은 다를 수 있습니다.

기본 시리얼 속도는 **115200**입니다. 펌웨어와 다르면 `--baud 921600`처럼 맞춰서 실행하세요. 네 장치를 연결할 때는 노트북 USB 포트 또는 충분한 전원을 제공하는 USB 허브를 사용합니다.

## 포트를 직접 지정하기

자동 검색은 USB 시리얼 포트를 대상으로 하므로 다른 USB 시리얼 장치가 함께 연결되어 있으면 원하는 장치만 선택하세요. 포트를 명시해 실행할 수도 있습니다.

```bash
.venv/bin/python -m local --ports /dev/ttyACM0 /dev/ttyACM1 /dev/ttyACM2 /dev/ttyACM3
```

연결 목록만 확인하려면:

```bash
.venv/bin/python -m local --list-ports
```

`/dev/ttyUSB0` 등 실제 할당된 경로를 사용할 수 있으며, Windows에서는 `--ports COM3 COM4 COM5 COM6`처럼 지정합니다. 자동 검색 이름과 USB 식별 정보는 `local/device_bindings.json`에 저장됩니다. 고유 USB 일련번호가 있는 보드는 tty 번호가 바뀌거나 재연결되어도 ESP 이름을 유지합니다. 일련번호가 없으면 USB 위치 또는 포트 경로를 기준으로 식별합니다.

직접 이름과 속도를 정하려면 `local/config.example.json`을 `local/config.local.json`으로 복사해 수정합니다. 이 파일이 있으면 기본 실행 시 자동으로 사용합니다. 예제는 네 개의 `/dev/ttyACM0`–`/dev/ttyACM3`를 사용합니다.

```bash
cp local/config.example.json local/config.local.json
.venv/bin/python -m local --config local/config.local.json
```

동일한 포트를 두 장치에 중복 등록하면 실행 전에 오류를 표시합니다. 시리얼 모니터 등 다른 프로그램이 같은 포트를 열고 있다면 닫고 실행하세요. 권한 오류가 나오면 해당 USB 장치의 접근 권한을 확인합니다.

## 저장 위치

기본 저장 위치는 실행 디렉터리와 관계없이 **`local/data/행동_YYMMDD_HHMMSS/`**입니다. 날짜는 한국 시간 기준 **수집 시작 버튼을 누른 시각**으로, 대기와 수집이 끝나는 시각이 아닙니다. 예를 들어 `lie_down`을 선택하고 2026년 10월 24일 19시 41분 30초에 시작하면 다음과 같이 저장됩니다.

```text
local/data/lie_down_261024_194130/
├── session.json          # action 행동 이름, 조건, 장치·USB 정보, 수신 건수, 오류, 저장 통계
├── esp-01.raw.csv        # 제외 전 원본 550개: 노트북 수신 시각 + ESP32 원문
├── esp-01.csv            # 앞뒤 제외 후 500개: CSI, RSSI, MAC 등 분리
├── esp-02.raw.csv
├── esp-02.csv
├── esp-03.raw.csv
├── esp-03.csv
├── esp-04.raw.csv
├── esp-04.csv
└── processed/
    ├── esp-01.csv        # 500행 전처리 결과 + 실제 경과시간
    ├── esp-02.csv
    ├── esp-03.csv
    └── esp-04.csv
```

`processed`는 GUI에서 결과를 표시하거나 headless 수집을 실행할 때 생성됩니다. 같은 세션을 나중에 **기존 결과 폴더 열기**로 열어 다시 전처리할 수 있습니다. 저장 위치는 `--data-dir /원하는/경로`로 변경할 수 있습니다.

각 ESP32 파일명은 기존처럼 `esp-01.csv` 등으로 유지됩니다. 기존 날짜 형식으로 저장한 폴더도 계속 열 수 있습니다. 같은 행동·같은 초의 폴더가 이미 있으면 덮어쓰지 않고 오류를 표시하며, 1초 후 다시 시작하면 됩니다.

## 취소와 오류

- 수집 중 USB 연결이 끊기면 해당 보드 오류를 기록하고 다른 보드는 계속 수집합니다. 목표를 못 채운 세션은 일부 누락으로 표시합니다.
- 유효 CSI가 10초 동안 오지 않거나 전체 수집이 600초를 넘으면 오류로 종료합니다. 종료 기준은 정상 동작 시 보드별 패킷 개수입니다.
- 취소하거나 앱을 닫으면 원본과 부분 결과를 저장한 뒤 종료합니다. 일부만 받은 경우에도 앞뒤 25개씩 제외하며, 부족한 데이터를 임의로 채우지 않습니다.
- 저장 파일은 자동 삭제하지 않습니다. 실행 중 비정상 전원 종료가 발생하면 `session.json`의 상태를 다음 실행에서 중단으로 표시하고 남은 원본을 유지합니다.

## 터미널에서만 수집

```bash
.venv/bin/python -m local --headless \
  --ports /dev/ttyACM0 /dev/ttyACM1 /dev/ttyACM2 /dev/ttyACM3 \
  --wait 5 --samples 500 --action lie_down
```

기본은 네 대 수집입니다. 일부만 사용할 때는 `--count 2`처럼 변경하세요. `--headless`에서도 전처리 CSV까지 저장합니다. `--action`을 생략하면 `none`이며, GUI로 실행할 때도 이 옵션으로 초기 행동을 지정할 수 있습니다.

## 검증

로컬 테스트는 가상 USB 네 대의 서로 다른 속도, 독립적인 목표 개수 종료, 분할 CSV 입력, 앞뒤 제외, 취소, 연결 끊김, 유효 CSI 미수신, 보드 이름 유지, 행동별 폴더명·기록, 중복 폴더 보호, headless 저장을 확인합니다.

원본 검증에서는 가상 디스플레이의 네 개 가상 USB 포트로 기본 **5초 대기 → 각각 550개 수집 → 500개 저장**과 개별/통합 그래프를 확인했습니다. 이 검증은 합성 CSI이며 실제 무선 측정은 아닙니다. 화면 검증 도구를 실행하면 `local/data/qa/local_desktop.png`와 `local/data/qa/local_packet_progress.png`에 결과를 저장합니다. 이 파일들은 Git에 포함하지 않습니다.

```bash
.venv/bin/python -m pytest -q tests/test_local_capture.py
# 디스플레이가 있는 Linux에서 네 개의 가상 USB로 화면 검증
.venv/bin/python -m local.qa_smoke
```
