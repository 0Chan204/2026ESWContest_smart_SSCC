# HomeVIS CSI 수신기

ESP32-C6가 AP gateway로 ping을 보내고 응답 패킷에서 Wi-Fi CSI를 측정해 USB CSV로 출력합니다.

| 항목 | 기본값 |
| --- | --- |
| 환경 | ESP-IDF 5.5.4 / ESP32-C6 / Flash 2MB |
| SSID | `HomeVIS-Local` |
| WPA2 비밀번호 | 공개 예제는 공백, 로컬 입력 필요 |
| 무선 / ping 목표 | HT20 / 25Hz |
| USB 출력 / 내장 RGB | 115200 baud / GPIO8 |

ESP-IDF 환경을 활성화하고 이 폴더에서 실행해 주세요.

```bash
idf.py menuconfig
idf.py build
idf.py -p /dev/ttyACM1 flash monitor
```

`HomeVIS CSI receiver`에서 SSID와 8–63바이트 WPA2 비밀번호를 [AP](../ap/README.md)와 동일하게 설정합니다. 최초 구성 시 `main/Kconfig.projbuild.example`에서 로컬 `main/Kconfig.projbuild`를 자동 생성합니다. 실제 접속 정보가 들어가는 로컬 Kconfig와 `sdkconfig`는 Git에서 제외합니다. 원본의 소스 내 Wi-Fi 비밀번호는 제거했습니다.

ping 목표 주기는 [main/main.c](main/main.c)의 `CSI_SEND_FREQUENCY_HZ`로 관리합니다. 실제 CSI 수신 빈도는 무선 상태와 USB 처리량에 따라 달라집니다. CSI 활성화·USB 보조 콘솔·115200 baud 설정은 `sdkconfig.defaults`에 포함되어 있습니다.

## CSV와 수집

줄바꿈으로 구분된 6열 CSV를 출력합니다.

```text
local_timestamp,"[허수0,실수0,허수1,실수1,...]",rssi,mac,first_word,len
```

`monitor`를 `Ctrl+]`로 종료한 뒤 [노트북·Pi 수집기](../../../ai-wifi-sensing/collection/README.md) 또는 [노트북 직접 수집기](../../../ai-wifi-sensing/collection/local/README.md)를 실행해 주세요. 수집기는 부팅 로그·손상된 CSI 등을 건너뛰고 유효 패킷만 목표 개수에 포함합니다.

내장 RGB는 부팅·최초 연결 전 흰색, Wi-Fi 오류 시 빨간색, 연결 후 CSI 준비 시 노란색, 센싱 시작 후 초록색입니다. 실제 보드에서는 AP 접속·CSV 형식·보드별 유효 패킷 수와 수신 빈도를 확인해 주세요.
