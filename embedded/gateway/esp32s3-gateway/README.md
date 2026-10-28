# HomeVIS ESP32-S3 USB 게이트웨이

ESP32-S3가 가전 전용 Wi-Fi를 만들고 USB 직렬 연결로 노트북의 MQTT 브로커까지 TCP를 중계합니다. 로컬 NTP도 제공합니다. ESP-IDF 5.5.4, ESP32-S3-WROOM-1 N16R8(16MB Flash, 8MB Octal PSRAM) 구성입니다.

```text
가전 → HomeVIS-Devices Wi-Fi → ESP32-S3 → USB → 노트북 → MQTT 브로커
       MQTT/NTP: 192.168.4.1                            → backend
```

코어 0은 Wi-Fi·TCP·NTP, 코어 1은 직렬 프레임·CRC를 처리합니다. MQTT 토픽과 JSON은 그대로 전달합니다. 일반 인터넷 공유/NAT 기능은 제공하지 않습니다.

## 로컬 환경 설정

Python 3.10 이상과 표준 라이브러리만 사용합니다. 이 폴더에서 실행해 주세요.

```bash
python3 host/configure_devices.py --broker-host 127.0.0.1
```

실제 가전망 비밀번호는 숨김 입력으로 받으며 `HOMEVIS_AP_PASSWORD` 환경변수로도 전달할 수 있습니다. `.env` 파일을 자동으로 읽지는 않습니다. `127.0.0.1`은 브로커가 중계 프로그램과 같은 노트북에서 실행되는 예시입니다. 다른 보드의 브로커를 사용하면 노트북에서 접근할 수 있는 주소를 지정해 주세요.

설정 도구는 `embedded/`를 기준으로 가전 6개 프로젝트와 S3의 로컬 `main/Kconfig.projbuild`를 생성하고, 기존 `sdkconfig`가 있으면 접속 설정을 함께 갱신합니다. GPIO·타깃·MQTT 인증·client ID는 유지합니다. 가전의 공개 예제에는 비밀번호 없이 SSID·MQTT·NTP만 반영합니다. 변경 전 파일은 `host/backups/`에 저장합니다.

| 파일 | 용도 | Git 포함 |
| --- | --- | --- |
| `main/Kconfig.projbuild.example` | 공개 AP/직렬 설정 예제 | 포함 |
| `sdkconfig.defaults` | S3 메모리·코어·콘솔 설정 | 포함 |
| `host/gateway.example.json` | 공개 호스트 설정 예제 | 포함 |
| `main/Kconfig.projbuild`, `sdkconfig`, `sdkconfig.old` | 로컬 접속 정보 | 제외 |
| `host/gateway.local.json`, `host/backups/` | 로컬 USB 포트·브로커 및 설정 백업 | 제외 |

설정 대상은 인덕션·주방 단독 조명·주방 조명/후드·정수기·방 조명·공기청정기입니다. **주방 단독 조명과 조명/후드는 같은 `light-02`를 사용하므로 둘 중 하나를 선택해 실행해 주세요.** 욕실은 이 도구의 대상이 아니며 해당 프로젝트의 `menuconfig`에서 별도로 설정합니다.

## 빌드와 실행

ESP-IDF 5.5.4 환경을 활성화한 뒤 이 폴더에서 실행해 주세요.

```bash
idf.py menuconfig
idf.py build
idf.py -p /dev/ttyACM0 flash
```

기본 데이터 통신은 보드의 COM/UART0 포트(TX GPIO43, RX GPIO44), 460800 baud, 8N1입니다. `HomeVIS USB gateway → Laptop serial transport`에서 Native USB Serial/JTAG를 선택할 수도 있습니다. 펌웨어와 호스트의 전송 방식·baud·실제 연결 포트를 맞춰 주세요. 앱 콘솔은 데이터와 섞이지 않도록 비활성화되어 있습니다.

업로드가 끝나면 같은 포트의 모니터를 닫고 중계 프로그램을 실행해 주세요.

```bash
python3 host/gateway.py --list-ports
python3 host/gateway.py --port /dev/ttyACM0 --baud 460800 --broker-host 127.0.0.1
```

명령줄 옵션은 `host/gateway.local.json`보다 우선합니다. 재부팅 후에도 유지되는 `/dev/serial/by-id/` 경로를 사용할 수 있습니다. `S3 handshake ready`와 가전별 `connected to broker` 로그로 연결을 확인해 주세요.

가전은 `192.168.4.1`에서 시각을 받은 뒤 MQTT를 시작합니다. 노트북 중계와 브로커를 먼저 실행하고, 각 가전도 새 설정으로 빌드·업로드해 주세요. 기본 AP/동시 연결 한도는 8개입니다. USB 단절 또는 heartbeat 만료 시 소켓을 닫고 새 handshake를 기다립니다.

## 검증

```bash
python3 -m unittest discover -s tests -v
```

가상 직렬 포트와 로컬 TCP를 사용해 프레임 호환·CRC·분할 수신, 직렬 포트 점유, NTP, 설정 갱신, 6개 MQTT 연결, 느린 연결 격리와 USB 재연결을 검사합니다. 실제 보드의 Wi-Fi·USB·브로커 왕복은 실물에서 확인해 주세요.
