"""
가짜 AI 판정 엔진(채은님 역할) 음성 명령 시뮬레이터입니다. (v0.6)

서버가 MQTT(home/voice/request)로 보낸 음성 문장을 받아, 아주 단순한 키워드 규칙으로 판단을 만들어
POST /api/v1/ai/decisions(voiceId 포함)로 돌려줍니다. 실제 판정 엔진이 준비되기 전에
"대시보드 -> 서버 -> 판정 엔진 -> 서버 -> 대시보드" 전체 흐름을 확인하는 용도입니다.

단순 규칙 (실제 모델 아님):
- "조명/불" + "켜/꺼"  -> 전등 on/off (욕실이면 light-00, 주방·부엌이면 light-02, 그 외 light-01), 확인 필요
- "환풍기" + "켜/꺼/강/중/약" -> 환풍기 on/off/set_speed (욕실이면 fan-02, 그 외 fan-01), 확인 필요
- "인덕션" + "꺼" -> 인덕션 끄기 (바로 실행) / "인덕션" + "켜" -> 인덕션 3단 켜기 (확인 없이 보내도 서버가 확인 창을 띄움)
- "공기청정기/공기" + "켜/꺼" -> 공기청정기 on/off, 확인 필요
- "물" -> 정수기는 직접 받으라고 안내 (제어 없음)
- 서버가 시작어("홈비스")를 떼고 보내므로 text에는 명령 문장만 있습니다 (wakeWord로 시작어 여부 확인 가능)
- 그 외 -> 기기 상태(GET /ai/device-states)를 보고 켜진 기기 수를 알려 줌

사용 방법 (맥, 저장소 폴더에서):
    source venv/bin/activate
    python tests/simulate_voice_ai.py                               # 같은 PC의 브로커·백엔드
    python tests/simulate_voice_ai.py --host 192.168.0.2 --api http://192.168.0.2:8000
    curl -X POST localhost:8000/api/v1/voice/commands -H 'Content-Type: application/json' -d '{"text":"욕실 조명 켜줘"}'
"""

import argparse
import json
import uuid
from datetime import datetime, timezone

import paho.mqtt.client as mqtt
import requests

REQUEST_TOPIC = "home/voice/request"


def new_client(client_id: str) -> mqtt.Client:
    try:
        return mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=client_id, clean_session=False)  # paho 2.x
    except AttributeError:
        return mqtt.Client(client_id=client_id, clean_session=False)  # paho 1.x


def _room(text: str) -> str:
    return "toilet" if ("욕실" in text or "화장실" in text) else ("room" if "방" in text else "kitchen")


def decide(text: str, api: str) -> dict:
    room = _room(text)
    room_label = {"toilet": "욕실", "room": "방", "kitchen": "주방"}[room]
    turn_off = "꺼" in text or "끄" in text

    if "인덕션" in text:
        if turn_off:
            return {"room": "kitchen", "announcement": "인덕션을 끌게요.",
                    "actions": [{"device": "stove", "action": "turn_off"}]}
        return {"room": "kitchen", "announcement": "인덕션을 3단으로 켤게요.",
                "actions": [{"device": "stove", "action": "turn_on", "level": 3}]}
    if "공기" in text:
        action = "off" if turn_off else "on"
        return {"room": "room", "announcement": f"공기청정기를 {'끌' if turn_off else '켤'}게요.", "requiresConfirmation": True,
                "actions": [{"device": "air_purifier", "deviceId": "air-01", "action": action}]}
    if "물" in text:
        return {"room": "kitchen", "announcement": "정수기에서 직접 받아 주세요.", "actions": []}
    if "조명" in text or "불" in text:
        # 욕실/화장실 -> light-00, 주방/부엌 -> light-02, 그 외(방) -> light-01
        if room == "toilet":
            light, light_room = "light-00", "toilet"
        elif "주방" in text or "부엌" in text:
            light, light_room = "light-02", "kitchen"
        else:
            light, light_room = "light-01", "room"
        action = "off" if turn_off else "on"
        verb = "끌게요" if turn_off else "켤게요"
        room_label_of = {"toilet": "욕실", "kitchen": "주방", "room": "방"}
        return {
            "room": light_room,
            "announcement": f"{room_label_of[light_room]} 조명을 {verb}.",
            "requiresConfirmation": True,
            "actions": [{"device": "light", "deviceId": light, "action": action}],
        }
    if "환풍기" in text:
        fan = "fan-02" if room == "toilet" else "fan-01"
        fan_room = "toilet" if fan == "fan-02" else "kitchen"
        label = "욕실" if fan == "fan-02" else "주방"
        speed = next((s for k, s in (("강", "high"), ("중", "mid"), ("약", "low")) if k in text), None)
        if turn_off:
            act, say = {"device": "fan", "deviceId": fan, "action": "off"}, f"{label} 환풍기를 끌게요."
        elif speed:
            act, say = {"device": "fan", "deviceId": fan, "action": "set_speed", "speed": speed}, f"{label} 환풍기 풍량을 바꿀게요."
        else:
            act, say = {"device": "fan", "deviceId": fan, "action": "on"}, f"{label} 환풍기를 켤게요."
        return {"room": fan_room, "announcement": say, "requiresConfirmation": True, "actions": [act]}

    try:
        items = requests.get(f"{api}/api/v1/ai/device-states", timeout=3).json()["items"]
        on = [d["deviceId"] for d in items if d["is_on"]]
        say = f"지금 켜져 있는 기기는 {len(on)}개예요." if on else "지금 켜져 있는 기기는 없어요."
    except Exception:
        say = f"{room_label} 상태를 확인하지 못했어요."
    return {"room": room, "announcement": say, "actions": []}


def main() -> None:
    parser = argparse.ArgumentParser(description="가짜 AI 판정 엔진 (음성 명령, docs/VOICE.md)")
    parser.add_argument("--host", default="localhost", help="MQTT 브로커 주소")
    parser.add_argument("--port", type=int, default=1883)
    parser.add_argument("--api", default="http://localhost:8000", help="백엔드 주소")
    args = parser.parse_args()

    def on_connect(client, userdata, flags, *rest):
        client.subscribe(REQUEST_TOPIC, qos=1)
        print(f"[가짜 판정 엔진] {args.host}:{args.port} 연결, {REQUEST_TOPIC} 구독")

    def on_message(client, userdata, msg):
        try:
            request = json.loads(msg.payload.decode("utf-8"))
        except ValueError:
            return
        decision = decide(request.get("text", ""), args.api)
        body = {
            "decisionId": f"sim-voice-{uuid.uuid4().hex[:10]}",
            "voiceId": request.get("voiceId"),
            "scenario": "voice_command",
            "confidence": 0.9,
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            **decision,
        }
        try:
            res = requests.post(f"{args.api}/api/v1/ai/decisions", json=body, timeout=5)
            print(f"[가짜 판정 엔진] \"{request.get('text')}\" -> {decision['announcement']} ({res.status_code}, {res.json().get('status')})")
        except Exception as exc:
            print(f"[가짜 판정 엔진] 판단 전송 실패: {exc}")

    client = new_client("voice-ai-simulator")
    client.on_connect = on_connect
    client.on_message = on_message
    client.connect(args.host, args.port, keepalive=30)
    try:
        client.loop_forever()
    except KeyboardInterrupt:
        print("\n[가짜 판정 엔진] 종료")


if __name__ == "__main__":
    main()
