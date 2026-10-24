"""One owner for controller events; bounded event-time reordering and nonblocking HTTP."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, replace
import heapq
import hashlib
import json
import time

from src.alert_service import AlertService
from src.control.automation_models import LightContext
from src.control.central_controller import CentralController
from src.control.identifiers import canonical_device, device_target
from src.control.scenario_models import BathroomFallState, FallBackendSignal
from src.llm.factory import create_llm
from src.llm.message_generator import LLMMessageGenerator
from src.models import RiskDecision, RiskLevel
from src.voice.tts import Pyttsx3TTS
from .backend_client import BackendClient, BackendError
from .alerts import AlertWorker
from .config import IntegrationConfig
from .decision_mapper import DecisionMapper, MappedDecision
from .outbox import Outbox
from .history import SQLiteDecisionHistory, SQLiteRoutineStorage
from .schemas import ContractError, device_items, number, decision_payload, iso_time
from .sensing import BehaviorObservation, join_behavior, location_observation
from .state_mapper import StateMapper


class IntegrationRuntime:
    """Call ingestion and advance/run_once on the same thread. HTTP workers only do I/O."""

    def __init__(self, config: IntegrationConfig, client: BackendClient, *, controller=None,
                 clock=time.time, fall_alert_service: AlertService | None = None):
        if client.config != config:
            raise ValueError("runtime/client configuration mismatch")
        self.config, self.client, self.clock = config, client, clock
        def make_alert_service():
            return (fall_alert_service if fall_alert_service is not None else
                    AlertService(LLMMessageGenerator(create_llm()), Pyttsx3TTS(),
                                 config.outbox_path.parent / "fall_alerts"))
        self._alert_worker = AlertWorker(make_alert_service) if config.async_alerts else None
        self.fall_alert_service = None if config.async_alerts else make_alert_service()
        self.outbox = Outbox(config.outbox_path, config.mode)
        self.controller = controller or CentralController(
            confidence_data_dir=config.outbox_path.parent / "controller",
            decision_history=SQLiteDecisionHistory(self.outbox, config.outbox_path.parent / "controller" / "decision_history.jsonl")
                if config.backend_v05 else None,
            routine_storage=SQLiteRoutineStorage(self.outbox) if config.backend_v05 else None)
        self.controller.realtime_engine.automatic_restore_enabled = config.backend_restore
        self.controller.bathroom_fall.backend_response_managed = bool(config.backend_fall_scenario)
        previous_incident = self.outbox.get_metadata("fall_incident")
        if (config.backend_fall_scenario and previous_incident and previous_incident["status"] == "resolved"
                and not previous_incident.get("rearmed")):
            self.controller.bathroom_fall._await_clear = True
            self.controller.bathroom_fall._incident_id = previous_incident["local_incident_id"]
            self.controller.bathroom_fall.state = BathroomFallState.RESOLVED_BY_CAREGIVER
        self.controller.morning_water.reserve_allowance = self.outbox.reserve_water
        self.state_mapper = StateMapper(config)
        self.decision_mapper = DecisionMapper(config, self.controller.decision_history)
        self.devices = {}
        # Keep devices as the public latest-received view for existing callers.
        self.latest_received_devices = self.devices
        self.evaluated_devices = {}
        self._device_faults = {}
        self.last_location = None
        self.last_decision = None
        self.diagnostics = []
        self.missing_inputs = {"bedtime_light": ["activity"], "morning_water": ["wake_activity"],
                               "bathroom_fall": ["fall_detected_or_activity_transition", "motion_state"]}
        self._events = []
        self._sequence = 0
        self._seen = {}
        self._queued = {}
        self._conflicts = {}
        self._latest_received_location = None
        self._latest_received_sample = None
        self._bedtime_interrupted_at = None
        self._last_location_message_at = None
        self._watermark = None
        self._last_advance = None
        self._backend_ok = False
        self._last_behavior_time = None
        self._last_fall_state = None
        self._light_requested = set()
        self._executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="homevis-http")
        self._poll_future = self._post_future = None
        self._post_record = None
        self._next_poll = 0.0
        self._poll_failures = 0
        self._fall_poll_future = None
        self._next_fall_poll = 0.0
        self._next_evaluation_audit = 0.0
        self._last_voice_state = None
        self._warning_context = {}

    def close(self):
        # HTTP workers have finite timeouts and never access the outbox/controller.
        self._executor.shutdown(wait=False, cancel_futures=True)
        if self._alert_worker is not None:
            self._alert_worker.close()
        self.outbox.close()

    def diagnostic(self, code, **detail):
        record = {"code": code, **detail}
        self.diagnostics.append(record)
        del self.diagnostics[:-1000]
        self.outbox.audit("diagnostic", self.clock(), record)

    def _enqueue(self, stream, timestamp, received_at, kind, value, raw):
        if timestamp > received_at:
            self.diagnostic("future_observation", stream=stream, measured_at=timestamp)
            return False
        fingerprint = json.dumps(raw, sort_keys=True, ensure_ascii=False)
        prior_fingerprint = self._queued.get((stream, timestamp))
        previous = self._seen.get(stream)
        if prior_fingerprint is not None:
            self.diagnostic("duplicate_observation" if prior_fingerprint == fingerprint else "conflicting_observation",
                            stream=stream, measured_at=timestamp)
            if prior_fingerprint != fingerprint:
                self._conflicts[stream] = max(timestamp, self._conflicts.get(stream, timestamp))
                if stream == "location":
                    self.controller.realtime_engine.sensing_invalid = True
                elif kind == "device":
                    self._queue_device_fault(stream, timestamp)
            return False
        if self._watermark is not None and timestamp < self._watermark:
            self.diagnostic("late_observation_dropped", stream=stream, measured_at=timestamp,
                            watermark=self._watermark, received_at=received_at)
            return False
        # The heap can reorder distinct observations within the allowed delay window.
        if previous is None or timestamp > previous[0]:
            self._seen[stream] = (timestamp, fingerprint)
        self._queued[(stream, timestamp)] = fingerprint
        self._sequence += 1
        # All available device observations (then faults) precede sensing at equal times.
        priority = 0 if kind == "device" else 2
        heapq.heappush(self._events, (timestamp, priority, self._sequence, stream, kind, value))
        return True

    def _queue_device_fault(self, stream, timestamp):
        """Queue unavailability, not an OFF sample or a fabricated updatedAt."""
        if self._watermark is not None and timestamp < self._watermark:
            self.diagnostic("late_device_fault", stream=stream, timestamp=timestamp)
            applied = self.evaluated_devices.get(stream)
            if applied is None or applied.measured_at > timestamp:
                return
            # Invalidate a disputed, already-applied cache at the processing cursor.
            # Do not replay the late measurement or invalidate a newer good sample.
            timestamp = self._watermark
        self._sequence += 1
        heapq.heappush(self._events, (timestamp, 1, self._sequence, stream, "device_fault", None))

    def _record_device_fault(self, stream, received_at):
        previous = self.devices.get(stream)
        cutoff = previous.measured_at if previous is not None else received_at
        self._device_faults[stream] = max(cutoff, self._device_faults.get(stream, cutoff))
        self._queue_device_fault(stream, received_at)

    def _bedtime_sample_valid(self, sample, at):
        minimum = self.controller.realtime_engine.config.MIN_CONFIDENCE
        return bool(sample is not None and sample.observation_valid is True and sample.detected
                    and sample.location == "room" and sample.confidence >= minimum
                    and 0 <= at - sample.timestamp < self.controller.realtime_engine.config.UNKNOWN_TIMEOUT
                    and sample.activity_observed is True and sample.activity == "lying"
                    and sample.activity_confidence is not None and sample.activity_confidence >= minimum
                    and sample.activity_timestamp is not None and sample.activity_timestamp <= at
                    and sample.activity_valid_until is not None and at < sample.activity_valid_until)

    def _interrupt_bedtime(self, timestamp):
        self._bedtime_interrupted_at = max(timestamp, self._bedtime_interrupted_at or timestamp)

    def ingest_location(self, payload, *, received_at=None, behavior: BehaviorObservation | None = None):
        received_at = self.clock() if received_at is None else received_at
        number(received_at, "received_at")
        self._last_location_message_at = max(received_at, self._last_location_message_at or received_at)
        try:
            observation = location_observation(payload, received_at, self.config)
        except (ValueError, TypeError) as exc:
            self.controller.realtime_engine.sensing_invalid = True
            self._interrupt_bedtime(received_at)
            self.diagnostic("invalid_location_payload", error=str(exc))
            return False
        sample = join_behavior(observation, behavior, self.config.behavior_max_skew)
        previous_sample = self._latest_received_sample
        if observation.measured_at <= received_at and (self._latest_received_location is None
                or observation.measured_at >= self._latest_received_location.measured_at):
            self._latest_received_location = observation
            self._latest_received_sample = sample
            if (previous_sample is not None and self._bedtime_sample_valid(previous_sample, previous_sample.timestamp)
                    and sample.activity_timestamp is not None):
                # A gap ends the OLD evidence; its discovery is not an interruption
                # inside the new episode. Location can trail behavior by max_skew,
                # and the first received new sample need not be first in event time.
                if sample.activity_timestamp > previous_sample.activity_valid_until:
                    self._interrupt_bedtime(previous_sample.activity_valid_until)
                elif sample.timestamp - previous_sample.timestamp >= self.controller.realtime_engine.config.UNKNOWN_TIMEOUT:
                    # Even long-lived behavior cannot cover missing location evidence.
                    # The engine's existing timeout/reset and request identity check
                    # also prevent the old episode from being resumed.
                    self._interrupt_bedtime(previous_sample.timestamp)
        if observation.measured_at <= received_at and not self._bedtime_sample_valid(sample, sample.timestamp):
            self._interrupt_bedtime(sample.timestamp)
        self.outbox.audit("location_received", received_at, {
            "raw": observation.raw, "measured_at": observation.measured_at,
            "received_at": received_at, "valid": observation.valid, "diagnostic": observation.diagnostic,
            "behavior": None if behavior is None else asdict(behavior),
        })
        # Late or malformed invalid results must not silently authorize restoration/normality.
        if not observation.valid:
            self.controller.realtime_engine.sensing_invalid = True
        enqueued = self._enqueue("location", observation.measured_at, received_at, "location",
                                 (observation, sample), {"location": observation.raw,
                                 "behavior": None if behavior is None else asdict(behavior)})
        if self._conflicts.get("location") == observation.measured_at:
            self._interrupt_bedtime(observation.measured_at)
        return enqueued

    def ingest_device_states(self, payload, *, fetched_at=None):
        fetched_at = self.clock() if fetched_at is None else fetched_at
        number(fetched_at, "fetched_at")
        try:
            items = device_items(payload)
        except (ValueError, TypeError) as exc:
            self.poll_failed("invalid_device_payload:" + str(exc), failed_at=fetched_at)
            return
        self._backend_ok = True
        present = set()
        for item in items:
            kind = canonical_device(item["device"])
            if item.get("updatedAt") is None or item.get("current_state") is None:
                if self.config.device_ids.get(kind) == item["deviceId"]:
                    present.add(kind)
                    self._record_device_fault(kind, fetched_at)
                    self.devices.pop(kind, None)
                    self.diagnostic("device_never_reported", device_id=item["deviceId"])
                continue
            try:
                observation = self.state_mapper.map(item, fetched_at)
                if self.config.backend_restore and kind == "stove":
                    observation = self._restore_evidence(observation)
            except (ValueError, TypeError) as exc:
                self.diagnostic("invalid_device_item", device_id=item["deviceId"], error=str(exc))
                if self.config.device_ids.get(kind) == item["deviceId"]:
                    self._record_device_fault(kind, fetched_at)
                continue
            self.outbox.audit("device_received", fetched_at, {
                "raw": item, "measured_at": observation.measured_at, "fetched_at": fetched_at,
                "diagnostics": observation.diagnostics,
            })
            if self.config.device_ids.get(kind) != item["deviceId"]:
                self.diagnostic("unmapped_device", device_id=item["deviceId"])
                continue
            present.add(kind)
            for code in observation.diagnostics:
                self.diagnostic(code, device_id=item["deviceId"])
            if observation.measured_at > fetched_at:
                # Reject the impossible timestamp but retain the latest poll's fault.
                self._record_device_fault(kind, fetched_at)
            previous = self.devices.get(kind)
            if observation.measured_at <= fetched_at and (previous is None or observation.measured_at >= previous.measured_at):
                self.devices[kind] = observation
                if (observation.measured_at > self._device_faults.get(kind, float("-inf"))
                        and observation.room is not None and observation.raw["online"]
                        and "device_snapshot_stale" not in observation.diagnostics
                        and (kind != "stove" or observation.appliance is not None)):
                    self._device_faults.pop(kind, None)
            self._enqueue(kind, observation.measured_at, fetched_at, "device", observation, item)
        for kind in self.config.device_ids.keys() - present:
            self._record_device_fault(kind, fetched_at)
            self.devices.pop(kind, None)
            self.diagnostic("device_missing", device=kind)

    def poll_failed(self, reason="backend_poll_failed", *, failed_at=None):
        self._backend_ok = False
        failed_at = self.clock() if failed_at is None else failed_at
        for kind in self.config.device_ids:
            self._record_device_fault(kind, failed_at)
        self.diagnostic(reason)

    def _restore_evidence(self, observation):
        """A sent command is not an ACK: require a later lower-level observation."""
        record = self.outbox.get_metadata("stove_reduction")
        raw = observation.raw
        level = raw["current_state"].get("level")
        eligible = False
        if (record and observation.measured_at >= record.get("accepted_at", record["requested_at"]) and raw["online"]
                and 0 <= self.clock() - observation.measured_at < self.config.device_max_age):
            eligible = bool(raw["online"] and raw["is_on"] and raw["control_state"] == "homevis"
                            and type(level) is int and type(record.get("previous_level")) is int
                            and level < record["previous_level"])
            if raw["control_state"] == "user" or not raw["is_on"]:
                self.outbox.set_metadata("stove_reduction", None)
        if observation.appliance is not None:
            return replace(observation, appliance=replace(
                observation.appliance, control_state="HOMEVIS_REDUCED" if eligible else "USER_OVERRIDE"))
        return observation

    def _restore_reservation(self, timestamp):
        morning = self.controller.morning_water
        morning.tick(timestamp)
        saved = self.outbox.water_reservation()
        if saved and saved["date"] == str(morning._date):
            morning.dispense_count = max(morning.dispense_count, saved["count"])
            morning.morning_water_dispensed = morning.dispense_count > 0

    def advance(self, now=None):
        now = self.clock() if now is None else now
        number(now, "now")
        if self._last_advance is not None and now < self._last_advance:
            raise ValueError("runtime clock cannot move backwards")
        self._last_advance = now
        watermark = now - self.config.allowed_lateness
        while self._events and self._events[0][0] <= watermark:
            timestamp, _, _, stream, kind, value = heapq.heappop(self._events)
            engine = self.controller.realtime_engine
            if kind == "location":
                observation, sample = value
                if engine.last_sensor_update is not None and timestamp <= engine.last_sensor_update:
                    self.diagnostic("duplicate_or_out_of_order_location", measured_at=timestamp)
                    continue
                self.last_location = observation
                self._restore_reservation(timestamp)
                self.controller.water_purifier_available = self.state_mapper.water_ready(
                    self.evaluated_devices.get("water_purifier"), timestamp)
                # Reusing a behavior result must not extend the observed activity duration.
                if (sample.activity_observed and self._last_behavior_time is not None
                        and sample.activity_timestamp <= self._last_behavior_time):
                    self.last_decision = engine.update_sensing(sample)
                    self.controller._collect_automation(self.last_decision)
                    self.controller._tick_scenarios(timestamp)
                else:
                    self.last_decision = self.controller.update_sensing(sample)
                    if sample.activity_observed:
                        self._last_behavior_time = sample.activity_timestamp
                self.missing_inputs = {
                    "bedtime_light": [] if sample.activity_observed and sample.activity != "unknown"
                                      and (sample.activity_confidence or 0) >= engine.config.MIN_CONFIDENCE else ["activity"],
                    "morning_water": [] if sample.activity_observed and sample.activity != "unknown"
                                      and (sample.activity_confidence or 0) >= engine.config.MIN_CONFIDENCE else ["wake_activity"],
                    "bathroom_fall": ([] if sample.activity_observed and sample.motion_state is not None
                                      and (sample.activity_confidence or 0) >= engine.config.MIN_CONFIDENCE
                                      and (sample.fall_detected is not None or sample.activity != "unknown")
                                      else ["fall_detected_or_activity_transition", "motion_state"]),
                }
                self.outbox.audit("location_applied", now, {
                    "measured_at": timestamp, "processed_at": now,
                    "missing_inputs": self.missing_inputs, "sample": asdict(sample)})
            elif kind in {"device", "device_fault"}:
                self.evaluated_devices[stream] = value
                if stream == "stove":
                    if value is None or value.appliance is None:
                        engine.appliance_invalid = True
                    elif engine.last_appliance_update is None or timestamp > engine.last_appliance_update:
                        self.last_decision = self.controller.update_appliance(value.appliance)
            self.collect_outputs(now)
        self._watermark = watermark
        self._queued = {key: value for key, value in self._queued.items()
                        if key[1] >= watermark or self._seen.get(key[0], (None,))[0] == key[1]}
        # A queued older valid sample must not erase a newer offline/invalid report.
        latest = self._latest_received_location
        if (latest is not None and not latest.valid) or (
                "location" in self._conflicts
                and (self.controller.realtime_engine.last_sensor_update or float("-inf")) <= self._conflicts["location"]):
            self.controller.realtime_engine.sensing_invalid = True
        if self.last_location is not None and self.last_location.valid_until is not None and watermark >= self.last_location.valid_until:
            self.controller.realtime_engine.sensing_invalid = True
        stove = self.evaluated_devices.get("stove")
        if stove is None or stove.appliance is None:
            self.controller.realtime_engine.appliance_invalid = True
        self.last_decision = self.controller.tick(watermark)
        self._evaluate_light(watermark)
        self.collect_outputs(now)
        self._schedule_warning(now)
        if now >= self._next_evaluation_audit:
            self.outbox.audit("evaluation", now, {**self.last_decision.to_dict(),
                                                 "sensing_health": self.sensing_health(now),
                                                 "fall_decision": asdict(self.controller.bathroom_decision)})
            self._next_evaluation_audit = now + self.config.evaluation_audit_interval
        return self.last_decision

    def sensing_health(self, now=None):
        """Separate message silence, old repeated measurements and explicit invalid results."""
        now = self.clock() if now is None else now
        limit = self.controller.realtime_engine.config.UNKNOWN_TIMEOUT
        observation = self._latest_received_location
        message_timeout = self._last_location_message_at is None or now - self._last_location_message_at >= limit
        measurement_stale = observation is None or now - observation.measured_at >= limit
        explicit_invalid = (self.controller.realtime_engine.sensing_invalid or observation is None
                            or not observation.valid
                            or (observation.valid_until is not None and now >= observation.valid_until)
                            or observation.sample.confidence < self.controller.realtime_engine.config.MIN_CONFIDENCE)
        return {
            "status": "message_timeout" if message_timeout else "invalid" if explicit_invalid
                      else "stale_measurement" if measurement_stale else "available",
            "message_timeout": message_timeout, "measurement_stale": measurement_stale,
            "explicit_invalid": explicit_invalid, "last_received_at": self._last_location_message_at,
            "measured_at": None if observation is None else observation.measured_at,
            "raw_location": None if observation is None else observation.raw["location"],
            "raw_confidence": None if observation is None else observation.raw["location_confidence"],
            "reason": None if observation is None else observation.raw.get("reason"),
            "applied_measured_at": self.controller.realtime_engine.last_sensor_update,
            "applied_observation_valid": bool(self.last_decision and self.last_decision.observation_valid),
            "last_confirmed_location": self.controller.realtime_engine.last_user_location,
        }

    def _evaluate_light(self, timestamp):
        observation, decision = self.evaluated_devices.get("light"), self.last_decision
        if (observation is None or observation.diagnostics
                or not 0 <= timestamp - observation.measured_at < self.config.device_max_age
                or not decision.observation_valid or decision.sensing_status != "valid"
                or self.last_location is None):
            return
        engine = self.controller.realtime_engine
        present = decision.user_location == observation.room
        key = (observation.measured_at, engine._location_since, present)
        self._light_requested = {item for item in self._light_requested if item[0] >= observation.measured_at}
        if key in self._light_requested:
            return
        if self.config.backend_fall_scenario:
            # Do not create new IDs while waiting for a just-sent light command's state.
            desired = ("on" if present else "off") if self.config.backend_v05 else ("turn_on" if present else "turn_off")
            for record in self.outbox.db.execute(
                    "SELECT payload FROM decisions WHERE expires_at>? AND status IN ('pending','sending','accepted')", (timestamp,)):
                if record[0] is not None and any(a["device"] == "light" and a["action"] == desired
                                               for a in json.loads(record[0])["actions"]):
                    return
        duration = 0 if engine._location_since is None else timestamp - engine._location_since
        sample = engine._sensing
        activity_confidence = (sample.activity_confidence or 0.0) if (
            sample.activity_observed and sample.activity_valid_until is not None
            and timestamp < sample.activity_valid_until) else 0.0
        result = self.controller.evaluate_light(LightContext(
            room=observation.room, light_on=observation.raw["is_on"], user_present=present,
            timestamp=timestamp, presence_duration=duration if present else 0,
            absence_duration=0 if present else duration, location_confidence=sample.confidence,
            activity_confidence=activity_confidence,
            sensor_consistency=self.controller.feature_extractor.sensor_consistency(
                engine._sensor_history, decision.user_location)))
        if result.action:
            self._light_requested.add(key)

    def _record_fall_transition(self, now):
        """Preserve AI state changes separately from backend incident/response stages.

        This is a local audit, not an invented HTTP event or permission to close an incident.
        Recovery emits no legacy ScenarioAction, so it must be observed independently.
        """
        if self.config.backend_fall_scenario:
            record = self.outbox.get_metadata("fall_incident")
            if (record and record["status"] == "resolved" and not record.get("rearmed")
                    and not self.controller.bathroom_fall._await_clear):
                self.outbox.set_metadata("fall_incident", {**record, "rearmed": True})
        decision = self.controller.bathroom_decision
        if decision is None or decision.state == self._last_fall_state:
            return
        state = decision.state.value
        if state == "NORMAL_BATHROOM_USE":
            self._last_fall_state = state
            return
        if state.startswith("FALL_"):
            self.outbox.latch_fall(decision.timestamp, decision.incident_id)
        incident = self.outbox.fall_incident()
        self.outbox.audit("fall_state_changed", now, {
            "previous_state": self._last_fall_state,
            "decision": asdict(decision), "measured_at": decision.timestamp, "processed_at": now,
            "local_incident_id": None if incident is None else incident["local_incident_id"],
            "backend_delivery": "backend_managed" if self.config.backend_fall_scenario else "fall_state_contract_unconfirmed",
            "backend_incident_status": incident.get("status") if incident and self.config.backend_fall_scenario else None,
        })
        self._last_fall_state = state

    def collect_outputs(self, now):
        self._record_fall_transition(now)
        outputs = self.controller.peek_outputs()
        if not outputs:
            return
        fall = any(getattr(o, "scenario", None) == "bathroom_fall" for o in outputs)
        if fall:
            first = min((o for o in outputs if getattr(o, "scenario", None) == "bathroom_fall"),
                        key=lambda o: o.timestamp)
            self.outbox.latch_fall(first.timestamp, (first.details or {}).get("incident_id"))
        emergency = (fall or self.outbox.fall_incident() is not None
                     or self.controller.realtime_engine.current_state == "DANGER")
        mapped = []
        for output in outputs:
            if self.config.backend_fall_scenario and getattr(output, "scenario", None) == "bathroom_fall":
                incident = self.outbox.fall_incident()
                output = replace(output, details={**(output.details or {}),
                                 "incident_id": incident["local_incident_id"]})
            sample = self.controller.realtime_engine._sensing
            evidence = (min(sample.confidence, sample.activity_confidence)
                        if sample is not None and sample.activity_observed and sample.activity_confidence is not None else None)
            stove = self.evaluated_devices.get("stove")
            level = None if stove is None else stove.raw["current_state"].get("level")
            result = self.decision_mapper.map(output, emergency=emergency, evidence_confidence=evidence, stove_level=level)
            if (self._is_backend_fall({"source_id": result.source_id, "payload": result.payload})
                    and self.outbox.fall_incident().get("confidence") is None):
                self.outbox.update_fall(confidence=result.payload["confidence"])
            if getattr(output, "action", None) == "reduce_power":
                stove = self.evaluated_devices.get("stove")
                result = replace(result, source={**result.source, "previous_level":
                    None if stove is None else stove.raw["current_state"].get("level")})
            mapped.append(result)
        self.outbox.save_batch(mapped, now, self.config.command_ttl)
        if self.config.backend_v05:
            for result in mapped:
                if result.payload is None and result.source.get("event") == "fall_user_alert_requested":
                    self.outbox.update(result.source_id, status="local_only")
        self.controller.acknowledge_outputs(outputs)
        for output in outputs:
            if getattr(output, "event", None) == "fall_user_alert_requested":
                self._speak_fall_user_alert(output, now)

    def _speak_fall_user_alert(self, output, now):
        """Stage-one local speech; later caregiver/report stages remain backend-owned."""
        decision = RiskDecision(
            RiskLevel.WARNING, situation="FALL_CONFIRMED", user_location="toilet",
            user_state="IN", duration=int((output.details or {}).get("unresponsive_seconds", 0)),
            decision_context={"scenario": "bathroom_fall", "stage": 1,
                              "incident_id": (output.details or {}).get("incident_id")},
        )
        if self._alert_worker is not None:
            incident = self.outbox.fall_incident()
            identity = incident["local_incident_id"] if incident else (output.details or {}).get("incident_id")
            if self.outbox.get_metadata("fall_user_alert_scheduled") == identity:
                return
            if not self._alert_worker.submit(decision, identity):
                self.diagnostic("fall_alert_queue_full")
            else:
                self.outbox.set_metadata("fall_user_alert_scheduled", identity)
            return
        try:
            result = self.fall_alert_service.handle(decision)
            detail = {"incident_id": (output.details or {}).get("incident_id"),
                      "result": result.to_dict()}
        except Exception as exc:
            detail = {"incident_id": (output.details or {}).get("incident_id"),
                      "error": f"{type(exc).__name__}: {exc}"}
        self.outbox.audit("fall_user_alert", now, detail)

    def receive_fall_backend_signal(self, signal: FallBackendSignal):
        """Host-supplied caregiver result; no unconfirmed HTTP listener is implied."""
        incident = self.outbox.fall_incident()
        if signal.caregiver_status not in {"safe", "no_response"}:
            raise ValueError("Integrated fall response requires an explicit caregiver_status")
        if (incident is None or signal.incident_id is None
                or signal.incident_id != incident["local_incident_id"]):
            raise ValueError("Caregiver response must identify the unresolved fall incident")
        if signal.caregiver_status == "safe" and self.controller.bathroom_fall._incident_id is None:
            if not self.config.backend_fall_scenario and not self.outbox.has_fall_action(signal.incident_id, "fall_caregiver_alert_requested"):
                raise ValueError("No persisted caregiver alert request for this fall incident")
            decision = self.controller.resolve_persisted_fall(signal)
        else:
            core_signal = (replace(signal, incident_id=self.controller.bathroom_fall._incident_id)
                           if self.config.backend_fall_scenario else signal)
            decision = self.controller.update_fall_backend_signal(core_signal)
        self.collect_outputs(signal.timestamp)
        if signal.caregiver_status == "safe":
            self.outbox.resolve_fall(signal.incident_id, signal.timestamp)
        self.outbox.audit("fall_caregiver_response", signal.timestamp, {
            "incident_id": signal.incident_id, "status": signal.caregiver_status,
            "state": decision.state.value,
        })
        return decision

    def receive_backend_fall_status(self, payload):
        """Adapter boundary for a configured backend status source; no guessed URL."""
        from .schemas import measured_time
        incident = self.outbox.fall_incident()
        if not isinstance(payload, dict) or not incident or not incident.get("fallIncidentId"):
            raise ContractError("no acknowledged backend fall incident")
        if payload.get("incidentId", payload.get("fallIncidentId")) != incident["fallIncidentId"]:
            raise ContractError("backend fallIncidentId mismatch")
        status = payload.get("status")
        if not isinstance(status, str):
            raise ContractError("backend incident status must be a string")
        timestamp = (payload.get("resolvedAt") if status == "resolved" else
                     payload.get("reportedAt") if status in {"reported", "auto_reported"} else
                     payload.get("guardianAlertedAt") or payload.get("detectedAt"))
        observed_at = measured_time(timestamp or payload.get("timestamp"))
        # The backend serializes timestamps to whole seconds.
        if not int(incident["started_at"]) <= observed_at <= self.clock():
            raise ContractError("invalid backend incident timestamp")
        if observed_at < int(incident.get("status_updated_at", incident["started_at"])):
            raise ContractError("out-of-order backend incident status")
        if status not in {"pending", "resolved", "reported", "auto_reported", "safe", "no_response"}:
            raise ContractError("unsupported backend incident status")
        self.outbox.update_fall(status_updated_at=observed_at, backend_status=status, stage=payload.get("stage"))
        if status in {"safe", "resolved"}:
            return self.receive_fall_backend_signal(FallBackendSignal(
                timestamp=max(self.clock(), self.controller.bathroom_fall._last or 0),
                caregiver_status="safe", incident_id=incident["local_incident_id"]))
        # confirmUrl includes a bearer token; never persist/log that field.
        self.outbox.audit("backend_fall_status", self.clock(), {
            "incidentId": incident["fallIncidentId"], "status": status, "stage": payload.get("stage")})

    def _queue_fall_announcement(self, detail, now):
        if not self.config.backend_v05:
            return
        incident = self.outbox.fall_incident()
        message = (detail.get("result") or {}).get("message")
        if (not incident or detail.get("incident_id") != incident["local_incident_id"]
                or not isinstance(message, str) or not message.strip() or incident.get("confidence") is None):
            return
        identity = "announcement:fall:" + incident["local_incident_id"]
        payload = decision_payload({
            "decisionId": "dec-" + hashlib.sha256(identity.encode()).hexdigest()[:32],
            "scenario": "fall_user_announcement", "confidence": incident["confidence"],
            "reason": "User confirmation speech for a detected fall", "timestamp": iso_time(now),
            "room": "toilet", "actions": [], "announcement": message.strip()[:500],
            "weatherBriefing": False, "expiresAt": iso_time(now + self.config.command_ttl)})
        source = {"timestamp": now, "type": "Announcement", "incident_id": incident["local_incident_id"]}
        self.outbox.save_batch([MappedDecision(identity, payload, None, source)], now, self.config.command_ttl)

    def _schedule_warning(self, now):
        if not self.config.backend_v05 or self._alert_worker is None:
            return
        decision = self.last_decision
        state = decision.state.value
        if state == self._last_voice_state:
            return
        self._last_voice_state = state
        if self.outbox.fall_incident() is not None or decision.action not in {"VOICE_WARNING", "EMERGENCY_WARNING"}:
            return
        identity = f"warning:{state}:{decision.timestamp}"
        sample = self.controller.realtime_engine._sensing
        if self._alert_worker.submit(decision.to_risk_decision(), identity):
            self._warning_context[identity] = {
                "timestamp": now, "type": "WarningAnnouncement", "state": state,
                "confidence": sample.confidence if sample is not None and decision.observation_valid else 0.0,
                "reason": decision.reason}

    def _queue_warning_announcement(self, detail, now):
        identity = detail.get("incident_id")
        source = self._warning_context.pop(identity, None)
        message = (detail.get("result") or {}).get("message")
        if source is None or not isinstance(message, str) or not message.strip():
            return
        payload = decision_payload({
            "decisionId": "dec-" + hashlib.sha256(identity.encode()).hexdigest()[:32],
            "scenario": "stove_safety_announcement", "confidence": source["confidence"],
            "reason": source["reason"], "timestamp": iso_time(source["timestamp"]), "room": "kitchen",
            "actions": [], "announcement": message.strip()[:500], "weatherBriefing": False,
            "expiresAt": iso_time(source["timestamp"] + self.config.command_ttl)})
        self.outbox.save_batch([MappedDecision(identity, payload, None, source)], now, self.config.command_ttl)

    def _is_backend_fall(self, row):
        return bool(self.config.backend_fall_scenario and row["source_id"].startswith("fall:")
                    and row["payload"] is not None)

    def _revalidate(self, row, now):
        if self._is_backend_fall(row):
            incident = self.outbox.fall_incident()
            # Send the recorded emergency even if polling or sensing later goes offline.
            return (None if incident and row["source_id"] == "fall:" + incident["local_incident_id"]
                    else "fall_incident_closed")
        if row["source"].get("type") == "Announcement":
            incident = self.outbox.fall_incident()
            return None if incident and row["source"].get("incident_id") == incident["local_incident_id"] else "fall_incident_closed"
        if row["source"].get("type") == "WarningAnnouncement":
            return (None if self.outbox.fall_incident() is None and self.last_decision is not None
                    and self.last_decision.state.value == row["source"]["state"] else "warning_no_longer_current")
        if not self._backend_ok:
            return "backend_state_unavailable"
        if self.last_location is None or not self.last_location.valid:
            return "sensing_invalid"
        engine = self.controller.realtime_engine
        if (engine.sensing_invalid or engine.last_sensor_update is None
                or now - engine.last_sensor_update >= engine.config.UNKNOWN_TIMEOUT
                or engine._sensing.confidence < engine.config.MIN_CONFIDENCE):
            return "sensing_stale_or_invalid"
        latest = self._latest_received_location
        if latest is not None and latest.valid_until is not None and now >= latest.valid_until:
            return "location_result_expired"
        if latest is not None and latest.measured_at >= engine.last_sensor_update and (
                not latest.valid or latest.sample.confidence < engine.config.MIN_CONFIDENCE
                or latest.sample.location != engine._sensing.location):
            return "location_changed_or_invalid_before_confirmation"
        if self.outbox.fall_incident() is not None:
            return "unresolved_fall_incident"
        for action in row["payload"]["actions"]:
            if action["action"] == "restore_power":
                if not self.config.backend_restore or not self.outbox.get_metadata("stove_reduction"):
                    return "restore_control_provenance_unconfirmed"
            observation = self.devices.get(action["device"])
            if action["device"] in self._device_faults:
                return "device_state_unavailable"
            if (action["device"] in self._conflicts and observation is not None
                    and observation.measured_at <= self._conflicts[action["device"]]):
                return "conflicting_device_state"
            if (observation is None or not observation.raw["online"] or observation.room is None
                    or not 0 <= now - observation.measured_at < self.config.device_max_age):
                return "device_state_stale_or_invalid"
            if self.config.backend_room(observation.room) != row["payload"]["room"]:
                return "device_room_mismatch"
            if action["device"] == "water_purifier":
                if not self.state_mapper.water_ready(observation, now):
                    return "water_not_ready"
                if engine._sensing.location != "kitchen" or engine.last_user_location != "kitchen":
                    return "user_not_confirmed_in_kitchen"
            elif action["device"] == "stove":
                if engine.appliance_invalid or not observation.raw["is_on"]:
                    return "stove_not_confirmed_on"
                if action["action"] == "restore_power":
                    evidence = self._restore_evidence(observation)
                    if (evidence.appliance is None or evidence.appliance.control_state != "HOMEVIS_REDUCED"
                            or engine._sensing.location != "kitchen" or engine.last_user_location != "kitchen"
                            or engine.current_state == "DANGER"):
                        return "restore_not_confirmed_safe"
                if action["action"] in {"reduce_power", "set_level"} and (
                        engine._sensing.location == "kitchen" or engine.last_user_location == "kitchen"):
                    return "user_returned_to_kitchen"
                if action["action"] == "set_level" and (
                        type(observation.raw["current_state"].get("level")) is not int
                        or observation.raw["current_state"]["level"] <= action["level"]):
                    return "stove_no_longer_above_requested_level"
            elif action["device"] == "light":
                target_room = observation.room
                source = row["source"]
                try:
                    source_device, source_room = device_target(
                        source.get("target", source.get("device", "")), source.get("room"))
                except ValueError:
                    return "light_target_mismatch"
                if source_device != "light" or source_room != target_room:
                    return "light_target_mismatch"
                scenario = source.get("scenario")
                if scenario == "bedtime_light_off" and action["action"] in {"turn_off", "off"}:
                    reason = self._revalidate_bedtime(source, target_room, now)
                    if reason:
                        return reason
                elif scenario == "light_auto_off" and action["action"] in {"turn_off", "off"}:
                    if engine._sensing.location == target_room:
                        return "user_returned_to_light_room"
                elif scenario == "light_auto_on" and action["action"] in {"turn_on", "on"}:
                    if engine._sensing.location != target_room or engine.last_user_location != target_room:
                        return "user_left_light_room"
                else:
                    return "unsupported_light_scenario"
                if (action["action"] in {"turn_off", "off"} and not observation.raw["is_on"]
                        or action["action"] in {"turn_on", "on"} and observation.raw["is_on"]):
                    return "light_already_in_requested_state"
        return None

    def _revalidate_bedtime(self, source, target_room, now):
        if (target_room != "room" or source.get("type") != "ScenarioAction"
                or not self.controller.bedtime_light.matches_current_request(source)):
            return "bedtime_request_no_longer_current"
        start = source["timestamp"] - source["details"]["lying_seconds"]
        if self._bedtime_interrupted_at is not None and self._bedtime_interrupted_at > start:
            return "bedtime_observation_interrupted"
        # Already-qualified request only: newer buffered behavior can maintain it,
        # but cannot advance the scenario clock or qualify a new request early.
        if not self._bedtime_sample_valid(self._latest_received_sample, now):
            return "bedtime_behavior_missing_or_expired"
        if self.controller.realtime_engine._sensing.location != target_room:
            return "user_left_room"
        return None

    def _prepare_send(self, now):
        rows = self.outbox.rows(status="pending")
        rows.sort(key=lambda row: not self._is_backend_fall(row))
        for row in rows:
            identity = row["source_id"]
            fall = self._is_backend_fall(row)
            if not fall and now >= row["expires_at"]:
                self.outbox.update(identity, status="expired", diagnostic="command_expired;execution_may_be_unknown")
                continue
            if not fall and row["attempts"] >= self.config.max_attempts:
                self.outbox.update(identity, status="exhausted", diagnostic="retry_limit;execution_may_be_unknown")
                continue
            if now < row["next_attempt"]:
                continue
            reason = self._revalidate(row, now)
            if reason:
                self.outbox.update(identity, diagnostic=reason,
                                   **({"status": "cancelled"} if reason in {"fall_incident_closed", "warning_no_longer_current"} else {}))
                continue
            self.outbox.update(identity, status="sending", attempts=row["attempts"] + 1,
                               next_attempt=now + (min(60, self.config.retry_interval * 2 ** min(row["attempts"], 5))
                                                   if fall else self.config.retry_interval), diagnostic=None)
            return row
        return None

    def _finish_send(self, row, response=None, error=None):
        if error is not None:
            retryable = isinstance(error, BackendError) and error.retryable
            self.outbox.update(row["source_id"], status="pending" if retryable else "failed",
                               diagnostic=str(error) if isinstance(error, BackendError) else "unexpected_transport_error")
            self.diagnostic("decision_send_failed", error=str(error) if isinstance(error, BackendError) else type(error).__name__)
            return
        if response.body.get("status") == "expired":
            self.outbox.update(row["source_id"], status="expired", response=response.body,
                               http_status=response.status, diagnostic="backend_expired_without_execution")
            return
        if self._is_backend_fall(row):
            incident_id = response.body.get("fallIncidentId")
            if not isinstance(incident_id, str) or not incident_id:
                self.outbox.update(row["source_id"], status="pending", diagnostic="fallIncidentId_missing")
                return
            self.outbox.update_fall(status="backend_managed", decisionId=row["payload"]["decisionId"],
                                    fallIncidentId=incident_id)
        if self.config.backend_restore:
            for action in response.body["actions"]:
                if action["device"] != "stove" or action["status"] != "sent":
                    continue
                if action["action"] in {"reduce_power", "set_level"}:
                    self.outbox.set_metadata("stove_reduction", {
                        "decisionId": row["payload"]["decisionId"], "requested_at": row["source"]["timestamp"],
                        "previous_level": row["source"].get("previous_level"), "accepted_at": self.clock()})
                elif action["action"] in {"restore_power", "turn_off"}:
                    self.outbox.set_metadata("stove_reduction", None)
        partial = any(action["status"] != "sent" for action in response.body["actions"])
        self.outbox.update(row["source_id"], status="accepted_partial" if partial else "accepted",
                           response=response.body, http_status=response.status,
                           diagnostic="execution_ack_not_provided" if not partial else "partial_failure_requires_reprocessing_contract")

    def dispatch_mock_once(self, now=None):
        """Deterministic mock-only convenience; live I/O uses run_once's worker."""
        if self.config.mode != "mock":
            raise ValueError("synchronous dispatch is mock-only")
        row = self._prepare_send(self.clock() if now is None else now)
        if row is not None:
            try:
                response = self.client.post_decision(row["payload"])
            except (BackendError, ContractError) as exc:
                self._finish_send(row, error=exc)
            else:
                self._finish_send(row, response=response)

    def run_once(self, now=None):
        """Nonblocking live poll/dispatch. The host calls this frequently, even without sensing."""
        now = self.clock() if now is None else now
        if self._alert_worker is not None:
            for detail in self._alert_worker.drain():
                if detail.get("incident_id") in self._warning_context:
                    self.outbox.audit("risk_user_alert", now, detail)
                    self._queue_warning_announcement(detail, now)
                else:
                    self.outbox.audit("fall_user_alert", now, detail)
                    self._queue_fall_announcement(detail, now)
        if self._fall_poll_future is not None and self._fall_poll_future.done():
            try:
                self.receive_backend_fall_status(self._fall_poll_future.result())
            except (BackendError, ContractError, ValueError) as exc:
                self.diagnostic("fall_status_unavailable", error=type(exc).__name__)
            finally:
                self._fall_poll_future = None
                self._next_fall_poll = now + self.config.poll_interval
        if self._poll_future is not None and self._poll_future.done():
            try:
                items, fetched_at = self._poll_future.result()
                self.ingest_device_states({"items": items}, fetched_at=fetched_at)
                self._poll_failures = 0
                self._next_poll = now + self.config.poll_interval
            except (BackendError, ContractError) as exc:
                self.poll_failed(str(exc))
                self._poll_failures += 1
                self._next_poll = now + (self.config.retry_interval
                    if self._poll_failures < self.config.max_attempts else self.config.poll_interval)
                if self._poll_failures >= self.config.max_attempts:
                    self._poll_failures = 0
            finally:
                self._poll_future = None
        if self._post_future is not None and self._post_future.done():
            try:
                self._finish_send(self._post_record, response=self._post_future.result())
            except (BackendError, ContractError) as exc:
                self._finish_send(self._post_record, error=exc)
            self._post_future = self._post_record = None
        decision = self.advance(now)
        if self._poll_future is None and now >= self._next_poll:
            def fetch():
                result = self.client.fetch_device_states()
                return result, self.clock()
            self._poll_future = self._executor.submit(fetch)
        if self._post_future is None:
            row = self._prepare_send(now)
            if row is not None:
                self._post_record = row
                self._post_future = self._executor.submit(self.client.post_decision, row["payload"])
        incident = self.outbox.fall_incident()
        if (self.config.fall_status_path and incident and incident.get("fallIncidentId")
                and self._fall_poll_future is None and now >= self._next_fall_poll):
            self._fall_poll_future = self._executor.submit(self.client.fetch_fall_status, incident["fallIncidentId"])
        return decision
