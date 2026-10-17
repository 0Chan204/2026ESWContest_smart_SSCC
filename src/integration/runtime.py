"""One owner for controller events; bounded event-time reordering and nonblocking HTTP."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
import heapq
import json
import time

from src.control.automation_models import LightContext
from src.control.central_controller import CentralController
from src.control.identifiers import canonical_device, device_target
from .backend_client import BackendClient, BackendError
from .config import IntegrationConfig
from .decision_mapper import DecisionMapper
from .outbox import Outbox
from .schemas import ContractError, device_items, number
from .sensing import BehaviorObservation, join_behavior, location_observation
from .state_mapper import StateMapper


class IntegrationRuntime:
    """Call ingestion and advance/run_once on the same thread. HTTP workers only do I/O."""

    def __init__(self, config: IntegrationConfig, client: BackendClient, *, controller=None, clock=time.time):
        if client.config != config:
            raise ValueError("runtime/client configuration mismatch")
        self.config, self.client, self.clock = config, client, clock
        self.outbox = Outbox(config.outbox_path, config.mode)
        self.controller = controller or CentralController(
            confidence_data_dir=config.outbox_path.parent / "controller")
        self.controller.realtime_engine.automatic_restore_enabled = False
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

    def close(self):
        # HTTP workers have finite timeouts and never access the outbox/controller.
        self._executor.shutdown(wait=False, cancel_futures=True)
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
            try:
                observation = self.state_mapper.map(item, fetched_at)
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
        stove = self.evaluated_devices.get("stove")
        if stove is None or stove.appliance is None:
            self.controller.realtime_engine.appliance_invalid = True
        self.last_decision = self.controller.tick(watermark)
        self._evaluate_light(watermark)
        self.collect_outputs(now)
        self.outbox.audit("evaluation", now, {**self.last_decision.to_dict(),
                                             "sensing_health": self.sensing_health(now),
                                             "fall_decision": asdict(self.controller.bathroom_decision)})
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
        if key in self._light_requested:
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
        decision = self.controller.bathroom_decision
        if decision is None or decision.state == self._last_fall_state:
            return
        state = decision.state.value
        if state == "NORMAL_BATHROOM_USE":
            self._last_fall_state = state
            return
        if state.startswith("FALL_"):
            self.outbox.latch_fall(decision.timestamp)
        incident = self.outbox.fall_incident()
        self.outbox.audit("fall_state_changed", now, {
            "previous_state": self._last_fall_state,
            "decision": asdict(decision), "measured_at": decision.timestamp, "processed_at": now,
            "local_incident_id": None if incident is None else incident["local_incident_id"],
            "backend_delivery": "fall_state_contract_unconfirmed",
            "backend_incident_status": None,
        })
        self._last_fall_state = state

    def collect_outputs(self, now):
        self._record_fall_transition(now)
        outputs = self.controller.peek_outputs()
        if not outputs:
            return
        fall = any(getattr(o, "scenario", None) == "bathroom_fall" for o in outputs)
        if fall:
            self.outbox.latch_fall(min(o.timestamp for o in outputs if getattr(o, "scenario", None) == "bathroom_fall"))
        emergency = (fall or self.outbox.fall_incident() is not None
                     or self.controller.realtime_engine.current_state == "DANGER")
        mapped = [self.decision_mapper.map(o, emergency=emergency) for o in outputs]
        self.outbox.save_batch(mapped, now, self.config.command_ttl)
        self.controller.acknowledge_outputs(outputs)

    def _revalidate(self, row, now):
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
        if latest is not None and latest.measured_at >= engine.last_sensor_update and (
                not latest.valid or latest.sample.confidence < engine.config.MIN_CONFIDENCE
                or latest.sample.location != engine._sensing.location):
            return "location_changed_or_invalid_before_confirmation"
        if self.outbox.fall_incident() is not None:
            return "unresolved_fall_incident"
        for action in row["payload"]["actions"]:
            if action["action"] == "restore_power":
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
                if action["action"] == "reduce_power" and (
                        engine._sensing.location == "kitchen" or engine.last_user_location == "kitchen"):
                    return "user_returned_to_kitchen"
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
                if scenario == "bedtime_light_off" and action["action"] == "turn_off":
                    reason = self._revalidate_bedtime(source, target_room, now)
                    if reason:
                        return reason
                elif scenario == "light_auto_off" and action["action"] == "turn_off":
                    if engine._sensing.location == target_room:
                        return "user_returned_to_light_room"
                elif scenario == "light_auto_on" and action["action"] == "turn_on":
                    if engine._sensing.location != target_room or engine.last_user_location != target_room:
                        return "user_left_light_room"
                else:
                    return "unsupported_light_scenario"
                if (action["action"] == "turn_off" and not observation.raw["is_on"]
                        or action["action"] == "turn_on" and observation.raw["is_on"]):
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
        for row in self.outbox.rows():
            if row["status"] != "pending":
                continue
            identity = row["source_id"]
            if now >= row["expires_at"]:
                self.outbox.update(identity, status="expired", diagnostic="command_expired;execution_may_be_unknown")
                continue
            if row["attempts"] >= self.config.max_attempts:
                self.outbox.update(identity, status="exhausted", diagnostic="retry_limit;execution_may_be_unknown")
                continue
            if now < row["next_attempt"]:
                continue
            reason = self._revalidate(row, now)
            if reason:
                self.outbox.update(identity, diagnostic=reason)
                continue
            self.outbox.update(identity, status="sending", attempts=row["attempts"] + 1,
                               next_attempt=now + self.config.retry_interval, diagnostic=None)
            return row
        return None

    def _finish_send(self, row, response=None, error=None):
        if error is not None:
            retryable = isinstance(error, BackendError) and error.retryable
            self.outbox.update(row["source_id"], status="pending" if retryable else "failed",
                               diagnostic=str(error) if isinstance(error, BackendError) else "unexpected_transport_error")
            return
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
        return decision
