# result_adapter.py  (보드 배포용 덮어쓰기 버전: 1초에 1건)
"""
지우님 판단 결과(재실 + 행동) -> 백엔드 최종 결과 형식 (발행 주제 home/edge/result)

원래 버전은 1초에 방별 3건을 보냈는데, 대시보드·AI 판정 엔진은 "가장 최근 결과 1건 = 집 전체 위치"로 읽기 때문에
사람이 부엌에 있어도 마지막에 온 toilet(present=false)이 최신 결과가 되어 재실이 안 보였습니다.
그래서 백엔드 명세(docs/AI-INTEGRATION.md)대로 1초에 1건을 보냅니다.

  사람 있음   : room=그 방,  present=true,  confidence, activity=그 방 노드의 행동
  아무도 없음 : room=null,   present=false, confidence, activity=none (빈 집의 낙상은 무시)
  판단 불가   : room=null,   present=null,  presenceReason, activity=노드 중 낙상이 있으면 fall(안전), 아니면 판단 가능한 노드 결과

  {"resultId": "res-20261027-075600", "observedAt": "...", "room": "kitchen", "present": true, "confidence": 0.81,
   "presenceReason": null, "activity": "none", "activityConfidence": 0.71, "activityReason": null,
   "modelVersion": "occ-67a75326+beh-f6ef98a2", "validSec": 5}
"""
from datetime import datetime

# (백엔드 방 이름, 우리 코드의 노드)
ROOMS = [("room", "r3"), ("kitchen", "r2"), ("toilet", "r4")]
ROOM_TO_NODE = dict(ROOMS)

# 우리 행동 -> 백엔드 activity 값
BEHAVIOR_TO_ACTIVITY = {"none": "none", "fall": "fall", "lie_down": "lie_down", "get_up": "get_up"}


def _reason_code(reason):
    """'poor_signal:r2,r3,r4' 처럼 노드 목록이 붙은 이유에서 앞의 코드만"""
    if not reason:
        return None
    return str(reason).split(":")[0]


def _activity(b):
    """노드 하나의 행동 결과 -> (activity, activityConfidence, activityReason)"""
    if b is None:
        return None, None, "behavior_off"
    if b.get("behavior") == "unknown":
        return None, None, b.get("reason") or "unknown"
    return BEHAVIOR_TO_ACTIVITY.get(b["behavior"], b["behavior"]), b.get("behavior_confidence"), None


class BackendResultBuilder:
    def __init__(self, model_version="local", valid_sec=5):
        self.model_version = model_version
        self.valid_sec = valid_sec

    def build(self, t_end, occ_final, beh_outputs):
        """
        occ_final   : 재실 최종 결과 dict (location, location_confidence, reason, time)
        beh_outputs : {노드: 행동 결과 dict} 또는 None (행동 추론을 끈 경우)
        반환        : 메시지 1개가 든 리스트 (occupancy_server.py가 리스트를 돌며 발행하므로 형식 유지)
        """
        observed_at = occ_final.get("time") or datetime.fromtimestamp(t_end).astimezone().isoformat(timespec="seconds")
        day = datetime.fromtimestamp(t_end).strftime("%Y%m%d")
        sec_of_day = int(t_end) - int(datetime.fromtimestamp(t_end).replace(hour=0, minute=0, second=0, microsecond=0).timestamp())
        loc = occ_final.get("location")
        conf = occ_final.get("location_confidence")
        conf = None if conf is None else round(float(conf), 3)
        beh = beh_outputs or {}

        msg = {"resultId": f"res-{day}-{sec_of_day:06d}", "observedAt": observed_at}
        if loc in ROOM_TO_NODE:
            msg.update(room=loc, present=True, confidence=conf, presenceReason=None)
            activity = _activity(None if beh_outputs is None else beh.get(ROOM_TO_NODE[loc]))
        elif loc == "empty":
            msg.update(room=None, present=False, confidence=conf, presenceReason=None)
            activity = ("none", None, None) if beh_outputs is not None else (None, None, "behavior_off")
        else:
            msg.update(room=None, present=None, confidence=None,
                       presenceReason=_reason_code(occ_final.get("reason")) or "unknown")
            if beh_outputs is None:
                activity = (None, None, "behavior_off")
            else:
                results = [_activity(beh.get(node)) for _, node in ROOMS]
                falls = [r for r in results if r[0] == "fall"]
                known = [r for r in results if r[0] is not None]
                if falls:  # 위치를 모를 때 낙상은 안전을 위해 그대로 내보냄
                    activity = max(falls, key=lambda r: r[1] or 0)
                elif known:
                    activity = max(known, key=lambda r: r[1] or 0)
                else:
                    activity = results[0]
        msg.update(activity=activity[0], activityConfidence=activity[1], activityReason=activity[2])
        msg.update(modelVersion=self.model_version, validSec=self.valid_sec)
        return [msg]
