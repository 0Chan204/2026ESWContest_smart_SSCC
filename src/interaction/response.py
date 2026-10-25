"""Short Korean responses from verified facts; no local speech or fabricated results."""
from .control import select_device

ROOM_NAMES = {"room": "방", "kitchen": "주방", "toilet": "욕실"}
DEVICE_NAMES = {"stove": "인덕션", "light": "전등", "fan": "환풍기", "water_purifier": "정수기", "air_purifier": "공기청정기"}
FALLBACK = "요청을 안전하게 확인하지 못했습니다. 기기와 원하시는 동작을 다시 말씀해 주세요."


class VoiceResponseService:
    @staticmethod
    def status(intent, facts, now, max_age, voice_id):
        query = intent["query"] or "device"
        if query == "weather":
            weather = facts["weather"]
            if not weather["available"]:
                return "현재 사용할 수 있는 날씨 정보가 없습니다."
            suffix = ""
            if weather["stale"]:
                suffix = (f" {weather['basedOn']} 기준의 오래된 정보입니다." if weather.get("basedOn")
                          else " 기준 시각이 확인되지 않은 오래된 정보입니다.")
            return weather["text"][:350] + suffix
        if query == "presence":
            sensing = facts["presence"]
            confidence = sensing.get("confidence")
            if confidence is None or confidence < 0.6 or sensing.get("present") is None:
                return "현재 재실 상태를 확실하게 확인할 수 없습니다."
            if not sensing["present"]:
                return "최신 센싱 결과에서 사람이 감지되지 않았습니다. 외출 여부까지 확인한 것은 아닙니다."
            room = ROOM_NAMES.get(sensing.get("room"))
            return f"최신 센싱 결과에서 {room}에 사람이 감지되었습니다." if room else "사람이 감지되었지만 구역은 확인되지 않았습니다."
        if query == "voice_history":
            previous = [v for v in facts["commands"] if v["voiceId"] != voice_id]
            if not previous:
                return "조회된 이전 음성 명령이 없습니다."
            return "직전 저장 발화는 “" + previous[0]["text"][:160] + "”입니다. 이 기록을 새 명령으로 실행하지는 않습니다."
        device = select_device(intent, facts["devices"], now, max_age)
        label = ROOM_NAMES[device["room"]] + " " + DEVICE_NAMES.get(device["device"], "기기")
        if device["device"] == "water_purifier":
            states = {"idle": "대기", "dispensing": "출수 중", "error": "오류"}
            return f"{label}의 보고 상태는 {states.get(device['current_state'].get('status'), '확인 불가')}입니다."
        text = f"{label}의 보고 상태는 {'켜짐' if device['is_on'] else '꺼짐'}입니다."
        if device["device"] == "air_purifier":
            from src.integration.state_mapper import purifier_state
            try:
                air = purifier_state(device, now, max_age)
            except (ValueError, TypeError, KeyError):
                return text + " 최신 유효한 공기질은 확인할 수 없습니다."
            text += f" 보고된 공기질은 {dict(good='좋음', normal='보통', bad='나쁨')[air['level']]}입니다."
            for key in ("pm25", "pm10"):
                if air["quality"].get(key) is not None:
                    text += f" {key} {air['quality'][key]:g}㎍/㎥."
        if device["device"] == "stove" and type(device["current_state"].get("level")) is int:
            text += f" 화력은 {device['current_state']['level']}단계입니다."
        return text

    @staticmethod
    def confirmation():
        return "실행 승인이나 취소는 백엔드 확인 화면에서 해 주세요. 이 발화로 기기를 실행하거나 낙상 상황을 종료하지 않습니다."
