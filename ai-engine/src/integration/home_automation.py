"""Device-only cooking rules and explicitly verified whole-home absence.

No PM thresholds, MQTT commands, inferred ownership, or confidence weight changes.
The backend/firmware priority hold protocol is currently missing; do not pretend
that issuing one ON/OFF command establishes an embedded override/away lock.
"""
from dataclasses import replace
import json
from uuid import uuid4

from .sensing import presence_evidence
from .state_mapper import purifier_state


class HomeAutomation:
    def __init__(self, runtime):
        self.runtime = runtime
        self.config = runtime.config.home_automation
        self.outbox = runtime.outbox
        self.cooking = self.outbox.get_metadata("cooking_episode")
        self.away = self.outbox.get_metadata("away_episode")
        # Discard an unsent candidate, including one from the former timed policy.
        if self.away and self.away.get("requested_at") is None:
            self.away = None
            self.outbox.set_metadata("away_episode", None)
        self.presence = None
        cursor = self.outbox.get_metadata("home_presence_cursor") or {}
        self._presence_at = cursor.get("at")
        self._presence_raw = cursor.get("raw")
        self._clean_since = self._clean_last = None
        self._last_health = None

    @property
    def away_active(self):
        return bool(self.away and self.away.get("requested_at") is not None)

    def _health(self, reason):
        if reason != self._last_health:
            self.runtime.diagnostic("home_automation", reason=reason)
            self._last_health = reason

    def health(self):
        return {"cooking_enabled": self.config.air_purifier_enabled and self.config.cooking_air_clean_enabled,
                "away_enabled": self.config.away_all_off_enabled,
                "whole_home_presence_verified": self.config.whole_home_presence_verified,
                "away_active": self.away_active,
                "stove_restore_locked": bool(self.outbox.get_metadata("away_restore_lock")),
                "embedded_priority_hold_contract_available": False,
                "last_diagnostic": self._last_health}

    def interrupt_presence(self):
        self.presence = None
        if self.away and not self.away_active:
            self.away = None
            self.outbox.set_metadata("away_episode", None)

    def observe_presence(self, observation):
        raw = observation.raw
        now, at = observation.received_at, observation.measured_at
        if not self.config.away_all_off_enabled:
            return
        if at > now:
            self.interrupt_presence()
            return
        if self._presence_at is not None and at <= self._presence_at:
            if at == self._presence_at and raw != self._presence_raw:
                self.interrupt_presence()
            return
        self._presence_at, self._presence_raw = at, raw
        self.outbox.set_metadata("home_presence_cursor", {"at": at, "raw": raw})
        evidence = presence_evidence(observation, allowed_lateness=self.runtime.config.allowed_lateness,
            max_age=self.runtime.controller.realtime_engine.config.UNKNOWN_TIMEOUT,
            min_confidence=self.config.away_min_confidence)
        if evidence is None:
            self.interrupt_presence()
            return
        if evidence["present"]:
            self.away = self.presence = None
            self.outbox.set_metadata("away_episode", None)
            return  # Returning home NEVER clears the stove ignition lock.
        if not self.config.whole_home_presence_verified:
            self.interrupt_presence()
            self._health("whole_home_absence_scope_unconfirmed")
            return
        self.presence = evidence
        if self.away is None:
            self.away = {"id": uuid4().hex, "started_at": at, "confidence": evidence["confidence"]}
        if not self.away_active:
            self.away["last_at"] = at
        self.outbox.set_metadata("away_episode", self.away)

    def _presence_fresh(self, now):
        return bool(self.presence and self.presence["at"] <= now < self.presence["valid_until"]
                    and now - self.presence["at"] < self.runtime.controller.realtime_engine.config.UNKNOWN_TIMEOUT)

    def _fresh_device(self, kind, now):
        observation = self.runtime.devices.get(kind)
        if (observation is None or not self.runtime._backend_ok
                or kind in self.runtime._device_faults or not observation.raw["online"]
                or observation.measured_at <= self.runtime._conflicts.get(kind, float("-inf"))
                or not 0 <= now - observation.measured_at < self.runtime.config.device_max_age):
            return None
        return observation

    @staticmethod
    def _stove_state_valid(stove):
        # Backend is_on=false with cooling means the burner has stopped heating.
        # Overheated/unknown are NOT normal cooking-end evidence.
        return bool(stove and stove.room == "kitchen" and
                    stove.raw["current_state"].get("state") in
                    ({"on"} if stove.raw["is_on"] else {"off", "cooling"}))

    def _row(self, scenario, episode, action=None):
        identity = f"home:{scenario}:{episode}:{action or 'all_off'}"
        row = self.outbox.db.execute("SELECT * FROM decisions WHERE source_id=?", (identity,)).fetchone()
        if row is None:
            return None
        return {**dict(row), **{key: json.loads(row[key]) if row[key] else None for key in ("source", "payload", "response")}}

    def _owned(self, air, quality):
        row = self._row("cooking_air_clean", self.cooking["id"], "on") if self.cooking else None
        control = quality["control"] or {}
        if (not row or not row["response"] or air.raw["control_state"] != "homevis"
                or control.get("publisher") != "api" or not control.get("commandId")
                or quality["reported_at"] < row["source"]["timestamp"]):
            return False
        return any(a.get("deviceId") == air.raw["deviceId"] and a.get("action") == "on"
                   and a.get("status") == "sent" and a.get("commandId") == control["commandId"]
                   for a in row["response"].get("actions", []))

    def note_manual_control(self, action, now):
        if action["device"] == "air_purifier":
            self.outbox.set_metadata("purifier_manual_intent", {"at": now, "action": action})

    def observe_devices(self, now):
        """A bad intermediate poll must break the clean hold even before tick()."""
        if self._clean_since is None:
            return
        stove, air = self._fresh_device("stove", now), self._fresh_device("air_purifier", now)
        try:
            quality = purifier_state(air.raw, now, self.runtime.config.device_max_age) if air else None
            valid = (self._stove_state_valid(stove) and not stove.raw["is_on"]
                     and air and air.room == "room" and air.raw["is_on"] and quality
                     and quality["level"] in {"good", "normal"} and self._owned(air, quality)
                     and not self._manual_override(quality))
        except (ValueError, TypeError, KeyError):
            valid = False
        if not valid:
            self._clean_since = self._clean_last = None

    def _manual_override(self, quality):
        manual = self.outbox.get_metadata("purifier_manual_intent")
        return bool((quality["control"] or {}).get("publisher") == "user"
                    or manual and self.cooking and manual["at"] >= self.cooking["on_at"])

    def tick(self, now):
        if not self._presence_fresh(now):
            self.interrupt_presence()
        if (self.config.away_all_off_enabled and self.config.whole_home_presence_verified and self.away
                and self._presence_fresh(now)):
            if not self.away_active:
                self.away["requested_at"] = now
                self.outbox.set_metadata("away_episode", self.away)
            # Persist the safety barrier BEFORE enqueue/network; a lost response is not permission to reignite.
            if not self.outbox.get_metadata("away_restore_lock"):
                self.outbox.set_metadata("away_restore_lock", {"episode_id": self.away["id"], "at": self.away["requested_at"]})
            if self.outbox.get_metadata("stove_reduction") is not None:
                self.outbox.set_metadata("stove_reduction", None)
            self._queue("away_all_off", self.away["id"], self.away["requested_at"], self.away["confidence"],
                        {**self.away, "last_sensing": self.presence["raw"]})
        if self.away_active:
            away_row = self._row("away_all_off", self.away["id"])
            if away_row and away_row["status"] in {"accepted", "accepted_partial"} and any(
                    item and item.raw["device"] in {"stove", "light", "fan", "air_purifier"}
                    and item.raw["is_on"] and item.measured_at > self.away["requested_at"]
                    for item in self.runtime.devices.values()):
                self._health("away_power_reported_on_priority_hold_contract_missing")
        if not (self.config.air_purifier_enabled and self.config.cooking_air_clean_enabled):
            return
        stove = self._fresh_device("stove", now)
        air = self._fresh_device("air_purifier", now)
        if not self._stove_state_valid(stove):
            self._clean_since = self._clean_last = None
            return
        is_on = stove.raw["is_on"]
        if self.cooking is None or stove.measured_at > self.cooking["last_at"]:
            if is_on and (self.cooking is None or not self.cooking["stove_on"]):
                self.cooking = {"id": uuid4().hex, "on_at": stove.measured_at, "stove_on": True, "last_at": stove.measured_at}
                self._clean_since = self._clean_last = None
            elif self.cooking:
                if self.cooking["stove_on"] and not is_on:
                    self.cooking["off_at"] = stove.measured_at
                    self.cooking["off_verified"] = stove.measured_at - self.cooking["last_at"] < self.runtime.config.device_max_age
                self.cooking.update(stove_on=is_on, last_at=stove.measured_at)
            if self.cooking:
                self.outbox.set_metadata("cooking_episode", self.cooking)
        if air is None or air.room != "room" or self.cooking is None:
            self._clean_since = self._clean_last = None
            return
        try:
            quality = purifier_state(air.raw, now, self.runtime.config.device_max_age)
        except (ValueError, TypeError, KeyError):
            self._clean_since = self._clean_last = None
            return
        if self.away_active or self.outbox.fall_incident() or self.runtime.controller.realtime_engine.current_state == "DANGER":
            self._clean_since = self._clean_last = None
            return
        if self._manual_override(quality):
            self._clean_since = self._clean_last = None
            self._health("purifier_manual_control_protected")
            return
        confidence = 1 - (now - min(stove.measured_at, air.measured_at, quality["reported_at"])) / self.runtime.config.device_max_age
        evidence = {"stove": stove.raw, "purifier": air.raw, "air_quality": quality["quality"],
                    "ownership_confirmed": self._owned(air, quality), "cooking_episode": self.cooking.copy()}
        observed_control = {"deviceId": air.raw["deviceId"], "is_on": air.raw["is_on"], "control": quality["control"],
                            "cooking_episode": self.cooking["id"], "ownership_confirmed": evidence["ownership_confirmed"]}
        if self.outbox.get_metadata("purifier_observed_control") != observed_control:
            self.outbox.set_metadata("purifier_observed_control", observed_control)
            self.outbox.audit("purifier_control_observed", now, observed_control)
        if is_on:
            self._clean_since = self._clean_last = None
            if not air.raw["is_on"]:
                on_row = self._row("cooking_air_clean", self.cooking["id"], "on")
                if on_row and on_row["response"]:
                    self._health("purifier_on_not_maintained_priority_hold_contract_missing")
                self._queue("cooking_air_clean", self.cooking["id"], now, confidence, evidence, action="on")
            return
        if (not self.config.air_purifier_off_on_good_or_normal or not self.cooking.get("off_verified")
                or not air.raw["is_on"] or quality["level"] not in {"good", "normal"}
                or not self._owned(air, quality)):
            self._clean_since = self._clean_last = None
            self._health("purifier_off_held_without_matching_command_provenance_or_clean_air")
            return
        at = min(stove.measured_at, air.measured_at, quality["reported_at"])
        if self._clean_last is None or at - self._clean_last >= self.runtime.config.device_max_age:
            self._clean_since = at
        if self._clean_last is None or at > self._clean_last:
            self._clean_last = at
        if at - self._clean_since >= self.config.air_purifier_clean_hold_seconds:
            evidence["clean_since"] = self._clean_since
            self._queue("cooking_air_clean", self.cooking["id"], now, confidence, evidence, action="off")

    def _queue(self, scenario, episode, now, confidence, evidence, *, action=None):
        if self._row(scenario, episode, action):
            return  # No new command for rejection, timeout, restart, or embedded reversal.
        result = self.runtime.decision_mapper.map_home_rule(scenario, episode, now, confidence, evidence, action=action)
        from src.interaction.explanation import decision_snapshot
        try:
            result = replace(result, source={**result.source, "snapshot": decision_snapshot(self.runtime)})
        except Exception as exc:
            result = replace(result, source={**result.source, "snapshot_error": type(exc).__name__})
        self.outbox.save_batch([result], now, self.runtime.config.command_ttl)
        self.runtime.controller.decision_history.save({"action_id": result.source_id, **result.source,
                                                      "confidence": confidence, "decisionId": (result.payload or {}).get("decisionId")})

    def revalidate(self, row, now):
        scenario, source = row["payload"]["scenario"], row["source"]
        if scenario == "away_all_off":
            return None if (self.config.away_all_off_enabled and self.config.whole_home_presence_verified
                and self.away_active and self.away["id"] == source["episode_id"] and self._presence_fresh(now)) else "whole_home_absence_no_longer_valid"
        if not self.cooking or self.cooking["id"] != source["episode_id"]:
            return "cooking_episode_changed"
        if (not self.config.air_purifier_enabled or not self.config.cooking_air_clean_enabled or self.away_active
                or self.outbox.fall_incident() or self.runtime.controller.realtime_engine.current_state == "DANGER"):
            return "higher_priority_control_active"
        stove, air = self._fresh_device("stove", now), self._fresh_device("air_purifier", now)
        if stove is None or air is None:
            return "cooking_device_unavailable"
        if (not self._stove_state_valid(stove) or air.room != "room"
                or air.raw["deviceId"] != row["payload"]["actions"][0]["deviceId"]):
            return "cooking_device_state_or_target_changed"
        try:
            quality = purifier_state(air.raw, now, self.runtime.config.device_max_age)
        except (ValueError, TypeError, KeyError):
            return "purifier_air_quality_unavailable"
        if self._manual_override(quality):
            return "purifier_manual_control_protected"
        if source["action"] == "on":
            return None if stove.raw["is_on"] and not air.raw["is_on"] else "cooking_on_no_longer_needed"
        if (not self.config.air_purifier_off_on_good_or_normal or not self.cooking.get("off_verified")
                or stove.raw["is_on"] or not air.raw["is_on"] or quality["level"] not in {"good", "normal"}
                or not self._owned(air, quality) or self._clean_since is None
                or self._clean_last - self._clean_since < self.config.air_purifier_clean_hold_seconds):
            return "cooking_off_no_longer_safe"
        return None
