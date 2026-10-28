# HomeVIS CSI AP

ESP32-C6를 CSI 수신 보드용 Wi-Fi AP로 사용합니다. AP는 DHCP와 gateway ping 응답을 제공하며 CSI CSV는 [수신기](../receiver/README.md)에서 출력합니다.

| 항목 | 기본값 |
| --- | --- |
| 환경 | ESP-IDF 5.5.4 / ESP32-C6 / Flash 2MB |
| SSID | `HomeVIS-Local` |
| WPA2 비밀번호 | 공개 예제는 공백, 로컬 입력 필요 |
| AP / gateway | `192.168.4.1/24` |
| 무선 | 채널 6, 802.11b/g/n, HT20 |
| 동시 접속 | 4대, 설정 범위 1–10대 |
| 콘솔 / 내장 RGB | 115200 baud / GPIO8 |

ESP-IDF 환경을 활성화하고 이 폴더에서 실행해 주세요.

```bash
idf.py menuconfig
idf.py build
idf.py -p /dev/ttyACM0 flash monitor
```

`HomeVIS Local AP`에서 SSID·비밀번호·채널·접속 수·RGB GPIO를 설정합니다. 최초 CMake 구성 시 `main/Kconfig.projbuild.example`에서 로컬 `main/Kconfig.projbuild`를 자동 생성합니다. 비밀번호는 8–63바이트이며 수신기와 같아야 합니다. 실제 접속 정보가 들어가는 로컬 Kconfig와 `sdkconfig`는 Git에서 제외합니다.

부팅 시 흰색, AP 준비 후 최초 연결 대기 시 노란색, 수신기가 연결되어 있으면 초록색, AP 중단·조회 실패·전체 연결 해제 시 빨간색으로 표시합니다. 초록색은 Wi-Fi 연결 상태이며 CSI 수집 성공은 수신기와 수집 프로그램에서 확인해 주세요.

AP를 먼저 켜고 수신기의 DHCP 연결을 확인한 뒤 [수집 프로그램](../../../ai-wifi-sensing/collection/README.md)에서 수신기 USB 포트를 선택해 주세요. AP 포트는 접속 로그만 출력합니다. ping 목표 주기는 수신기의 `CSI_SEND_FREQUENCY_HZ`에서 관리하며 실제 수신 빈도는 장비와 무선 환경에서 확인해야 합니다.
