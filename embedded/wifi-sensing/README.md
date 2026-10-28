# HomeVIS CSI 펌웨어

`HomeVIS-CSI_Collection/firmware`에서 이관한 ESP32-C6 펌웨어입니다. AP 보드는 수신 보드용 Wi-Fi·DHCP·ping 응답을 제공하고, 수신 보드는 응답 패킷의 CSI를 USB 시리얼로 출력합니다.

```text
ESP32-C6 AP (HomeVIS-Local)
    ↕ Wi-Fi / gateway ping
ESP32-C6 수신기 1 … N
    ├─ USB → 노트북 직접 수집
    └─ USB → Raspberry Pi C 에이전트 → 노트북 수집 서버
```

| 폴더 | 역할 | 기본값 |
| --- | --- | --- |
| [ap](ap/README.md) | 수집용 Wi-Fi AP | `HomeVIS-Local`, 채널 6, 최대 4대 |
| [receiver](receiver/README.md) | CSI 측정·CSV 출력 | AP gateway ping 목표 25Hz, USB 115200 baud |

두 프로젝트 모두 ESP-IDF 5.5.4·ESP32-C6·2MB Flash 설정을 사용합니다. `dependencies.lock`과 컴포넌트 매니페스트를 포함하며, 실제 의존성 소스와 빌드 결과는 포함하지 않습니다.

## 설정과 빌드

각 프로젝트 폴더에서 ESP-IDF 환경을 활성화한 뒤 실행해 주세요.

```bash
idf.py menuconfig
idf.py build
idf.py -p /dev/ttyACM0 flash monitor
```

AP는 `HomeVIS Local AP`, 수신기는 `HomeVIS CSI receiver` 메뉴를 사용합니다. **두 보드의 SSID와 WPA2 비밀번호를 동일하게 설정해 주세요.** 공개 비밀번호 기본값은 비어 있으며, 8–63바이트의 로컬 비밀번호를 입력해야 실행할 수 있습니다. SSID는 1–32바이트입니다.

처음 구성할 때 `main/Kconfig.projbuild.example`에서 로컬 `main/Kconfig.projbuild`를 자동 생성합니다. 실제 설정은 `menuconfig`가 저장한 `sdkconfig`에 반영됩니다. 기존 `sdkconfig`가 있으면 Kconfig의 default보다 우선하므로 설정 변경 후 유효값을 확인해 주세요. `Kconfig.projbuild`, `sdkconfig`, 빌드 폴더는 Git에서 제외합니다.

AP 포트에는 접속 로그가 나오며, **수집 프로그램에는 수신기 포트를 선택**해야 합니다. `monitor`를 `Ctrl+]`로 종료한 뒤 수집기를 실행해 주세요. 실제 포트는 보드마다 다릅니다.

## 수집과 실시간 추론

[수집 프로그램](../../ai-wifi-sensing/collection/README.md)은 노트북 USB 직결과 Pi 분산 수집을 지원하며, 기본적으로 보드마다 유효 패킷 550개 중 앞뒤 25개씩을 제외해 500개를 저장합니다. [로컬 수집 안내](../../ai-wifi-sensing/collection/local/README.md)에서 행동 라벨·포트 선택 방법을 확인하실 수 있습니다.

실시간 재실·행동 추론용 Pi 실행 코드는 기존 [ai-wifi-sensing/pi](../../ai-wifi-sensing/pi/)에 있습니다. 데이터 수집 도구와 구분해서 사용해 주세요. 이 CSI AP의 `HomeVIS-Local` 설정은 가전 USB 게이트웨이의 `HomeVIS-Devices` 설정과 별도로 관리합니다.

원본 코드와 원본 로컬 환경값·수집 데이터는 기존 경로에 보존했습니다. 이번 이관에는 실제 환경값, CSV, 수집 대기열, 바이너리, 캐시와 IDE 설정을 포함하지 않았습니다.

## 이관 검증 · 2026-10-28

AP와 수신기 모두 ESP-IDF 5.5.4에서 컴파일·링크·이미지 크기 검사를 통과했으며 컴파일 경고와 오류가 없었습니다. 검증은 `/tmp`의 별도 복사본에서 공개 설정과 기존 의존성 캐시로 진행했습니다. 실제 비밀번호는 사용하지 않았고, 보드 업로드와 실제 무선 수신 검증은 수행하지 않았습니다.
