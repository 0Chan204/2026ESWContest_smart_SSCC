# mqtt_util.py
"""
MQTT 연결 도우미 (Pi 의 edge_node.py, 서버의 occupancy_server.py, replay_test.py 가 함께 사용)

MQTT 란?
  '브로커'라는 우편국 하나를 두고, 보내는 쪽은 '주제(topic)'를 붙여 메시지를 올리고(publish),
  받는 쪽은 관심 있는 주제를 구독(subscribe)해서 받는 방식.
  → Pi 3대는 브로커 주소만 알면 되고, 나중에 통합 서버가 생겨도 그쪽이 같은 주제를 구독하면 끝.

이 프로젝트에서 쓰는 주제 (prefix 기본값 = "wifi/occupancy")
  wifi/occupancy/features/r2   Pi(r2) → 서버 : 1초마다 특성 19개
  wifi/occupancy/features/r3   Pi(r3) → 서버
  wifi/occupancy/features/r4   Pi(r4) → 서버
  wifi/occupancy/state         서버 → 누구나 : 최종 재실 결과 (time / location / location_confidence)
  wifi/occupancy/truth         replay_test.py → 서버 : (테스트용) 실제 정답 라벨

필요한 라이브러리: paho-mqtt
  맥북 : pip install paho-mqtt
  Pi   : sudo apt install python3-paho-mqtt
paho-mqtt 1.x 와 2.x 는 사용법이 조금 달라서, 이 파일이 둘 다 지원하도록 감싸 준다.
"""

import json
import threading

try:
    import paho.mqtt.client as mqtt
except ImportError:  # 설치 안내를 친절하게
    raise SystemExit("[오류] paho-mqtt 가 없습니다.  맥북: pip install paho-mqtt  /  "
                     "Pi: sudo apt install python3-paho-mqtt")

DEFAULT_PREFIX = "wifi/occupancy"


def topic_features(prefix: str, node: str = "+") -> str:
    """'+' 는 MQTT 와일드카드: features/+ = 모든 노드의 특성 주제를 한 번에 구독"""
    return f"{prefix}/features/{node}"


def topic_state(prefix: str) -> str:
    return f"{prefix}/state"


def topic_truth(prefix: str) -> str:
    return f"{prefix}/truth"


class MqttLink:
    """
    브로커 연결 하나. 끊기면 자동으로 다시 연결하고, 다시 연결되면 구독도 자동으로 다시 한다.

      link = MqttLink("192.168.0.10", 1883, client_id="edge-r3")
      link.subscribe("wifi/occupancy/features/+", handler)   # handler(topic, dict)
      link.start()
      link.publish("wifi/occupancy/state", {"location": "room"})
    """

    def __init__(self, host: str, port: int = 1883, client_id: str = "", verbose: bool = True):
        self.host, self.port, self.verbose = host, port, verbose
        self.connected = threading.Event()
        self._subs = {}   # topic → handler

        # paho 2.x 는 콜백 API 버전을 반드시 지정해야 하고, 1.x 에는 그 인자가 없다
        try:
            self.client = mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
                                      client_id=client_id)
        except AttributeError:
            self.client = mqtt.Client(client_id=client_id)

        # 콜백 인자 개수가 버전마다 달라서 *args 로 받는다 (두 버전 모두 args[1] 이 결과 코드)
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.client.on_message = self._on_message
        self.client.reconnect_delay_set(min_delay=1, max_delay=10)   # 끊기면 1~10초 간격으로 재시도

    # ---------- 콜백 ----------
    def _on_connect(self, client, userdata, *args):
        rc = args[1] if len(args) > 1 else 0
        if str(rc) not in ("0", "Success"):
            print(f"[MQTT] 연결 거부됨 ({rc}) — 브로커 설정을 확인하세요")
            return
        self.connected.set()
        for topic in self._subs:            # 재연결 때도 구독을 다시 걸어 줌
            client.subscribe(topic, qos=0)
        if self.verbose:
            print(f"[MQTT] 연결됨: {self.host}:{self.port}")

    def _on_disconnect(self, client, userdata, *args):
        self.connected.clear()
        if self.verbose:
            print(f"[MQTT] 연결 끊김 → 자동 재연결 시도 중 ({self.host}:{self.port})")

    def _on_message(self, client, userdata, msg):
        try:
            payload = json.loads(msg.payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return   # 형식이 깨진 메시지는 무시
        for pattern, handler in self._subs.items():
            if mqtt.topic_matches_sub(pattern, msg.topic):
                handler(msg.topic, payload)

    # ---------- 사용자용 ----------
    def subscribe(self, topic: str, handler):
        self._subs[topic] = handler
        if self.connected.is_set():
            self.client.subscribe(topic, qos=0)

    def start(self, wait_sec: float = 5.0) -> bool:
        """
        백그라운드 연결 시작. wait_sec 동안 연결을 기다려 보고 결과를 돌려준다.
        (연결이 안 돼도 프로그램은 계속 돌고, 브로커가 살아나면 자동으로 붙는다)
        """
        self.client.connect_async(self.host, self.port, keepalive=30)
        self.client.loop_start()
        ok = self.connected.wait(wait_sec)
        if not ok:
            print(f"[MQTT] {wait_sec:g}초 안에 {self.host}:{self.port} 에 연결하지 못했습니다. "
                  f"계속 재시도합니다. (브로커 주소/방화벽/브로커 실행 여부 확인)")
        return ok

    def publish(self, topic: str, payload: dict, retain: bool = False):
        """
        QoS 0 = '한 번 보내고 끝'. 1초마다 새 값이 오므로 하나쯤 빠져도 문제없고, 가장 가볍다.
        retain=True 면 브로커가 마지막 값을 기억했다가 새 구독자에게 바로 준다 (state 주제에 사용).
        """
        text = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
        self.client.publish(topic, text, qos=0, retain=retain)

    def stop(self):
        self.client.loop_stop()
        self.client.disconnect()
