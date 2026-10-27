# presence_tracker.py
"""
재실 유지 단계 (엔진 결과 → 최종 결과)
=====================================

왜 필요한가?
  엔진(occupancy_engine.py)은 '지금 이 순간의 신호'만 보고 판단한다.
  그래서 사람이 가만히 앉아 있거나 자고 있으면 신호 변화가 거의 없어 empty / unknown 이 나온다.
  이 단계는 "한 번 확실히 들어온 사람은, 다른 곳에서 보이기 전까지는 그 자리에 있다"고 보고
  마지막으로 확실히 감지된 장소를 일정 시간 동안 유지한다.

동작 규칙
  [유지 시작] 같은 장소가 '신뢰도 ≥ 0.85' 로 '3초 연속' 관측되면 그 장소를 유지 대상으로 정한다.
              (엔진의 출력 기준 θ≈0.75 보다 엄격하게 → 잠깐의 오판이 30분짜리 오답이 되는 것을 막음)
  [유지 갱신] 유지 중인 장소가 다시 관측되면(신뢰도 무관) 마지막 관측 시각을 갱신한다.
  [유지 계속] 관측 결과가 empty 이거나, unknown 중 아래 '유지하는 이유'이면 유지 장소를 출력한다.
  [유지 종료] ① 다른 장소가 3초 연속 관측됨 (확실하면 그 장소로 교체, 애매하면 유지만 해제)
              ② 마지막 관측 후 장소별 최대 시간이 지남: 방 7시간 / 화장실 30분 / 부엌 20분
              ③ (선택, 기본 꺼짐) empty 가 N초 연속 → release_empty_sec

unknown 이유별 처리
  low_confidence  → 유지  (가만히 있거나 이동 중일 가능성)
  poor_signal     → 유지  (일시적인 데이터 불량)
  warming_up      → 유지  (서버 재시작 직후. 저장해 둔 상태로 복원)
  node_offline    → 60초까지 유지, 그 뒤로는 unknown  (센서 없이 재실을 주장하지 않음)
  config_mismatch → 유지 안 함, 바로 unknown  (설치 오류이므로 숨기면 안 됨)

유지 중 신뢰도
  = 마지막 관측 때 신뢰도 × (1 − 경과 시간 / 최대 유지 시간)
  → 시간이 지날수록 선형으로 줄어 최대 시간에 0 이 된다.
    (예: 방 0.90 → 3.5시간 뒤 0.45 / 화장실 0.90 → 15분 뒤 0.45)

상태 저장
  판단에 필요한 건 '유지 장소, 그 장소의 마지막 관측 시각과 신뢰도' 세 가지뿐이다.
  서버가 재시작돼도 이어 가도록 이 세 값만 작은 JSON 파일에 저장해 두고, 켤 때 다시 읽는다.
"""

import json
import os
import time
from datetime import datetime

PLACES = ("room", "kitchen", "toilet")

DEFAULT_MAX_HOLD_SEC = {"room": 7 * 3600, "toilet": 30 * 60, "kitchen": 20 * 60}
HOLD_REASONS = {"low_confidence", "poor_signal", "warming_up"}   # 이 이유의 unknown 은 유지


def _iso(t):
    return datetime.fromtimestamp(t).astimezone().isoformat(timespec="seconds")


class PresenceTracker:
    def __init__(self, max_hold_sec=None, enter_conf=0.85, enter_sec=3, offline_grace_sec=60,
                 release_empty_sec=None, state_path=None, log=print):
        """
        max_hold_sec      : 장소별 최대 유지 시간(초)
        enter_conf/sec    : 유지 시작 조건 (이 신뢰도 이상이 이 초 수만큼 연속)
        offline_grace_sec : node_offline 이 이 시간까지는 유지, 넘으면 unknown
        release_empty_sec : empty 가 이만큼 연속이면 유지 해제 (None = 사용 안 함)
        state_path        : 상태 저장 파일 (None = 저장 안 함)
        """
        self.max_hold = dict(DEFAULT_MAX_HOLD_SEC, **(max_hold_sec or {}))
        self.enter_conf, self.enter_sec = enter_conf, enter_sec
        self.offline_grace = offline_grace_sec
        self.release_empty = release_empty_sec
        self.state_path = state_path
        self.log = log

        # ---- 유지 상태 (저장 대상) ----
        self.held = None          # 유지 중인 장소
        self.held_conf = None     # 그 장소를 마지막으로 관측했을 때의 신뢰도
        self.last_seen = None     # 그 장소를 마지막으로 관측한 시각 (t_end)
        # ---- 연속 횟수 (저장 안 함) ----
        self.run_loc, self.run_n, self.strong_n = None, 0, 0
        self.empty_run, self.offline_run = 0, 0
        self._last_saved = 0
        self._load()

    # ------------------------------------------------------
    def _load(self):
        if not self.state_path or not os.path.exists(self.state_path):
            return
        try:
            with open(self.state_path, encoding="utf-8") as f:
                s = json.load(f)
        except (OSError, json.JSONDecodeError):
            return
        held, last_seen = s.get("held"), s.get("last_seen")
        if held in PLACES and last_seen is not None:
            if time.time() - last_seen <= self.max_hold[held]:
                self.held, self.held_conf, self.last_seen = held, float(s.get("held_conf", 0.5)), float(last_seen)
                self.log(f"[유지] 저장된 상태 복원: {held} (마지막 관측 {_iso(last_seen)})")

    def _save(self, t_end, force=False):
        """유지 장소가 바뀌면 바로, 아니면 10초에 한 번만 파일에 기록 (디스크 부담 최소화)"""
        if not self.state_path or (not force and t_end - self._last_saved < 10):
            return
        tmp = self.state_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"held": self.held, "held_conf": self.held_conf, "last_seen": self.last_seen}, f)
        os.replace(tmp, self.state_path)       # 쓰는 도중 꺼져도 파일이 깨지지 않게
        self._last_saved = t_end

    def _set_held(self, t_end, loc, conf, why):
        if loc != self.held:
            self.log(f"[유지] {self.held or '-'} → {loc or '-'}  ({why})")
        changed = loc != self.held
        self.held, self.held_conf, self.last_seen = loc, conf, (t_end if loc else None)
        self._save(t_end, force=changed)

    # ------------------------------------------------------
    def update(self, t_end: int, obs: dict) -> dict:
        """
        obs : 엔진 출력 {"time", "location", "location_confidence", ("reason")}
        반환: 최종 출력 dict
        """
        loc, conf = obs["location"], obs["location_confidence"]
        reason = obs.get("reason", "")
        kind = reason.split(":")[0] if reason else ""

        # ---------- 1) 장소가 관측됨 ----------
        if loc in PLACES:
            self.empty_run = self.offline_run = 0
            if loc == self.run_loc:
                self.run_n += 1
                self.strong_n = self.strong_n + 1 if conf >= self.enter_conf else 0
            else:
                self.run_loc, self.run_n = loc, 1
                self.strong_n = 1 if conf >= self.enter_conf else 0

            if loc == self.held:
                self.held_conf, self.last_seen = conf, t_end          # 유지 갱신
                self._save(t_end)
            elif self.strong_n >= self.enter_sec:
                self._set_held(t_end, loc, conf, f"신뢰도 ≥ {self.enter_conf} 로 {self.enter_sec}초 연속")
            elif self.held and self.run_n >= self.enter_sec:
                # 다른 곳에서 3초째 보임 → 예전 장소엔 없다. 확신은 부족하니 새로 유지하진 않음
                self._set_held(t_end, None, None, f"{loc} 에서 {self.enter_sec}초 연속 관측")
            return self._out(obs, source="observed")

        # ---------- 2) empty / unknown ----------
        self.run_loc, self.run_n, self.strong_n = None, 0, 0
        self.empty_run = self.empty_run + 1 if loc == "empty" else 0
        self.offline_run = self.offline_run + 1 if kind == "node_offline" else 0

        if self.held:
            elapsed = t_end - self.last_seen
            if elapsed >= self.max_hold[self.held]:
                self._set_held(t_end, None, None, f"최대 유지 시간 {self.max_hold[self.held] // 60}분 경과")
            elif self.release_empty and self.empty_run >= self.release_empty:
                self._set_held(t_end, None, None, f"empty {self.release_empty}초 연속")

        can_hold = self.held is not None and (
            loc == "empty"
            or kind in HOLD_REASONS
            or (kind == "node_offline" and self.offline_run <= self.offline_grace))
        if can_hold:
            return self._held_out(t_end, obs)
        return self._out(obs, source="observed")

    # ------------------------------------------------------
    def _out(self, obs, source):
        out = dict(obs)
        out["source"] = source
        out["observed"] = obs["location"]
        return out

    def _held_out(self, t_end, obs):
        limit = self.max_hold[self.held]
        elapsed = t_end - self.last_seen
        conf = self.held_conf * max(0.0, 1.0 - elapsed / limit)
        out = {
            "time": obs["time"],
            "location": self.held,
            "location_confidence": round(conf, 3),
            "source": "held",                         # 관측이 아니라 '유지'로 낸 결과
            "observed": obs["location"],              # 이번 초에 엔진이 실제로 본 것
            "last_seen": _iso(self.last_seen),        # 유지 장소를 마지막으로 관측한 시각
            "hold_remaining_sec": int(max(0, limit - elapsed)),
        }
        if obs.get("reason"):
            out["observed_reason"] = obs["reason"]
        return out
