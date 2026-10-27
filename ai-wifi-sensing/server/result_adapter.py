# result_adapter.py
"""
우리 판단 결과(재실 + 행동) → 백엔드가 정한 최종 결과 형식 (발행 주제 home/edge/result)

백엔드 형식 (방 하나당 메시지 하나)
  {
    "resultId": "res-20261027-000123",      하루 안에서 증가하는 번호. 재시작해도 겹치지 않게 '그날 0시부터의 초 × 3 + 방 번호'로 만든다
    "observedAt": "2026-10-27T21:00:02+09:00",
    "room": "kitchen",                      room / kitchen / toilet
    "present": true,                        이 방에 사람이 있는가 (판단 불가면 null)
    "confidence": 0.91,
    "presenceReason": null,                 판단 불가일 때만 이유 (warming_up, node_offline, poor_signal, config_mismatch, low_confidence)
    "activity": "fall",                     행동: none / fall / lie_down / get_up (판단 불가면 null)
    "activityConfidence": 0.94,
    "activityReason": null,                 판단 불가일 때만 이유
    "modelVersion": "...",
    "validSec": 5
  }

한 초에 3개(방·부엌·화장실)를 낸다. 낙상은 재실 판단과 무관하게 그 노드에서 감지되면 그 방 메시지에 실리도록,
행동은 재실 결과가 아니라 '그 방의 노드' 결과를 그대로 쓴다.

※ 아래 매핑·규칙은 백엔드와 확정되지 않은 부분이 있어 한 곳(이 파일 위쪽)에 모아 두었다.
"""
from datetime import datetime

# (백엔드 방 이름, 우리 코드의 노드) — 순서가 resultId 의 방 번호
ROOMS = [("room", "r3"), ("kitchen", "r2"), ("toilet", "r4")]

# 우리 행동 → 백엔드 activity 값 (백엔드 값 목록이 정해지면 여기만 고치면 됨)
BEHAVIOR_TO_ACTIVITY = {"none": "none", "fall": "fall", "lie_down": "lie_down", "get_up": "get_up"}


def _reason_code(reason):
    """'poor_signal:r2,r3,r4' 처럼 노드 목록이 붙은 이유에서 앞의 코드만"""
    if not reason:
        return None
    return str(reason).split(":")[0]


class BackendResultBuilder:
    def __init__(self, model_version="local", valid_sec=5):
        self.model_version = model_version
        self.valid_sec = valid_sec

    def build(self, t_end, occ_final, beh_outputs):
        """
        occ_final   : 재실 최종 결과 dict (location, location_confidence, reason, time)
        beh_outputs : {노드: 행동 결과 dict} 또는 None (행동 추론을 끈 경우)
        반환        : 방별 메시지 3개의 리스트
        """
        observed_at = occ_final.get("time") or datetime.fromtimestamp(t_end).astimezone().isoformat(timespec="seconds")
        day = datetime.fromtimestamp(t_end).strftime("%Y%m%d")
        sec_of_day = int(t_end) - int(datetime.fromtimestamp(t_end).replace(hour=0, minute=0, second=0, microsecond=0).timestamp())
        loc = occ_final.get("location")
        conf = occ_final.get("location_confidence")
        out = []
        for idx, (room, node) in enumerate(ROOMS):
            msg = {"resultId": f"res-{day}-{sec_of_day * 3 + idx:06d}", "observedAt": observed_at, "room": room}
            if loc in (None, "unknown"):
                msg.update(present=None, confidence=None, presenceReason=_reason_code(occ_final.get("reason")) or "unknown")
            else:
                msg.update(present=(loc == room), confidence=None if conf is None else round(float(conf), 3),
                           presenceReason=None)
            b = None if beh_outputs is None else beh_outputs.get(node)
            if b is None:
                msg.update(activity=None, activityConfidence=None, activityReason="behavior_off")
            elif b["behavior"] == "unknown":
                msg.update(activity=None, activityConfidence=None, activityReason=b.get("reason") or "unknown")
            else:
                msg.update(activity=BEHAVIOR_TO_ACTIVITY.get(b["behavior"], b["behavior"]),
                           activityConfidence=b.get("behavior_confidence"), activityReason=None)
            # 사람이 없다고 판단된 방에서 감지된 낙상은 무시 (재실이 판단 불가(null)일 때는 안전을 위해 그대로 둔다)
            if msg["present"] is False and msg["activity"] == "fall":
                msg.update(activity="none", activityConfidence=None, activityReason=None)
            msg.update(modelVersion=self.model_version, validSec=self.valid_sec)
            out.append(msg)
        return out
