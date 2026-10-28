# HomeVIS 임베디드 장치

ESP-IDF 5.5.4 기반 가전 시연 펌웨어와 ESP32-S3 USB 게이트웨이입니다. `HomeVIS-EM.devices`의 최신 작업 파일에서 소스·공개 설정·기존 테스트·라이선스만 선별했습니다. 원본은 보존했습니다.

## 프로젝트

| 폴더 | 보드 / Flash | 기능과 기기 ID |
| --- | --- | --- |
| [room/room-light](room/room-light/README.md) | ESP32-C6 / 4MB | 방 WS2812B 조명, `light-01` |
| [room/air-purifier](room/air-purifier/README.md) | ESP32-C6 / 4MB | MQ135 공기질 측정·팬 릴레이, `air-01` |
| [kitchen/induction](kitchen/induction/README.md) | ESP32-C6 / 8MB | 엔코더·LED 화력·OLED·온도센서, `induction-01` |
| [kitchen/kitchen-light](kitchen/kitchen-light/README.md) | ESP32-C6 / 4MB | 주방 단독 조명, `light-02` |
| [kitchen/kitchen-light-hood](kitchen/kitchen-light-hood/README.md) | ESP32-C6 / 4MB | 주방 조명·후드 릴레이, `light-02` / `fan-01` |
| [kitchen/water-purifier](kitchen/water-purifier/README.md) | ESP32-C6 / 4MB | 터치·한글 OLED·LED 출수 시연, `water-01` |
| [toilet/toilet-light-fan](toilet/toilet-light-fan/README.md) | ESP32-C3 / 4MB | 욕실 조명·환풍기, `light-00` / `fan-02` |
| [gateway/esp32s3-gateway](gateway/esp32s3-gateway/README.md) | ESP32-S3 N16R8 / 16MB | 가전 Wi-Fi·NTP·USB TCP 중계 |

주방 단독 조명과 조명/후드는 같은 `light-02`를 사용하므로 둘 중 하나를 선택해 주세요. `dummy-data/`는 통합 저장소에 있던 서버 연동 예제를 보존한 폴더이며 실제 장치 업로드에는 위 프로젝트를 사용합니다.

## 환경 설정

펌웨어는 `.env` 대신 ESP-IDF Kconfig를 사용합니다. `main/Kconfig.projbuild.example`에서 로컬 `main/Kconfig.projbuild`가 최초 구성 시 자동 생성됩니다. 실제 Wi-Fi·MQTT 인증값은 로컬 파일 또는 `idf.py menuconfig`에 입력해 주세요. `sdkconfig.defaults`에는 공개 가능한 보드 설정만 들어 있습니다.

- 가전 6개 프로젝트는 SSID `HomeVIS-Devices`, MQTT `mqtt://192.168.4.1:1883`, NTP `192.168.4.1`의 게이트웨이 구성을 기본으로 합니다. AP 비밀번호는 공개 예제에 없습니다. [게이트웨이 설정 도구](gateway/esp32s3-gateway/README.md)로 로컬 설정을 생성할 수 있습니다.
- 욕실은 SSID가 비어 있고 MQTT `mqtt://192.168.0.2:1883`, NTP `pool.ntp.org`인 독립 설정입니다. 사용 환경에 맞게 `menuconfig`에서 변경해 주세요.
- 게이트웨이 호스트의 기본 브로커는 `127.0.0.1:1883`입니다. 다른 보드에서 실행되는 브로커는 `--broker-host`나 `host/gateway.local.json`으로 지정해 주세요.
- 기존 `sdkconfig`가 있으면 Kconfig의 `default`보다 우선합니다. 설정 변경 후에는 `menuconfig`에서 유효값을 확인해 주세요. 물리 보드마다 MQTT client ID도 고유해야 합니다.

실제 `.env`, `Kconfig.projbuild`, `sdkconfig`, `sdkconfig.old`, `*.local.json`, 자격증명 백업, 빌드 폴더, 캐시, IDE 개인 설정은 이관하지 않았으며 `.gitignore`에서 제외합니다. 로컬 환경값은 원본 경로에 보존되어 있습니다.

## 빌드와 검증

ESP-IDF 5.5.4 환경을 활성화한 뒤 원하는 프로젝트 폴더에서 실행해 주세요.

```bash
idf.py menuconfig
idf.py build
idf.py -p /dev/ttyACM0 flash monitor
```

포트와 타깃은 위 표 및 실제 보드에 맞춰 주세요. S3 게이트웨이는 데이터 포트를 중계에 사용하므로 `flash` 후 별도 호스트 프로그램을 실행합니다. 기존 경로의 빌드 캐시는 재사용하지 않습니다.

각 가전의 기존 호스트 테스트는 해당 프로젝트에서 실행합니다. ESP-IDF의 cJSON 소스만 사용하므로, 일반 개발용 셸에서 `IDF_PATH`를 설치된 ESP-IDF 5.5.4 경로로 지정해 주세요. ESP-IDF 활성화로 교차 도구의 `ld`가 먼저 선택되는 환경에서는 호스트 C 테스트의 링크가 실패할 수 있습니다. 이 경우 활성화하지 않은 일반 셸에서 실행해 주세요.

```bash
IDF_PATH=/path/to/esp-idf ASAN_OPTIONS=detect_leaks=0 sh tests/run.sh
```

게이트웨이는 해당 폴더에서 `python3 -m unittest discover -s tests -v`로 검사합니다. 공기청정기의 `tests/check_backend.py`는 통합 저장소의 `backend/` 스키마를 기본으로 확인하며 Pydantic v2가 필요합니다. 보드 업로드와 실제 배선·센서·브로커 연동은 실물에서 확인해 주세요.

## 시연 사진

첨부받은 JPG 원본 6장을 [docs/images](docs/images/)에 보관하고 각 기기 README에 연결했습니다.

| 장치 | 사진 |
| --- | --- |
| 공기청정기 | [공기청정기](docs/images/air-purifier.jpg) |
| 실내 조명 | [실내 조명](docs/images/room-light.jpg) |
| 인덕션 | [인덕션](docs/images/induction.jpg) |
| 정수기 | [정수기](docs/images/water-purifier.jpg) |
| 주방 후드·조명 | [주방 후드·조명](docs/images/kitchen-light-hood.jpg) |
| 화장실 Wi-Fi 센싱 모듈 | [화장실 전체 모듈](docs/images/toilet-wifi-sensing.jpg) |

인덕션은 실제 가열 없이 LED로 화력을 표시하고, 정수기는 실제 출수 없이 LED·OLED로 동작을 시연합니다. 화장실 사진의 Raspberry Pi 센싱 코드는 [ai-wifi-sensing](../ai-wifi-sensing/README.md)에 있으며, 이 원본의 욕실 펌웨어는 조명·환풍기 제어만 담당합니다.

변경 단위별 커밋 제목·본문·파일 범위는 [COMMIT_GUIDE.md](COMMIT_GUIDE.md)에 정리했습니다.

## 이관 검증 결과 · 2026-10-28

- ESP-IDF 5.5.4로 실제 가전 7개와 S3 게이트웨이 총 8개 프로젝트를 `/tmp`의 별도 폴더에서 공개 설정만으로 새로 빌드했습니다.
- 가전 7개 모델 테스트, 게이트웨이 8개 테스트, 공기청정기 ↔ 통합 백엔드 스키마 검사를 통과했습니다.
- 공개 설정의 인증값 공백, 원본 로컬 비밀번호 미포함, 사진 6장의 원본 일치, README 로컬 링크와 `git diff --check`를 확인했습니다.
- 실제 보드 업로드·배선·센서·브로커 왕복 검증은 수행하지 않았습니다.
