# Additional central-controller scenarios

The direct-controller examples below preserve the original internal stage API.
The continuous runner now follows the team's backend v0.5 workflow: one
`fall_detected` decision, backend-owned SMS/escalation, and incident polling for
`resolved`. It does not send the local caregiver/report stages. See
[continuous runner](continuous_runner.md) for the current deployment behavior.

`CentralController.update_sensing`, `update_appliance`, and `tick` continue to
return the existing kitchen `RealtimeDecision`. New results are separate:

```python
from src.control import (
    CentralController, FallBackendSignal, ScenarioConfig, SensingUpdate,
)

controller = CentralController(
    scenario_config=ScenarioConfig(),
    water_purifier_available=True,  # Set only after checking device readiness.
)
kitchen_decision = controller.update_sensing(
    SensingUpdate("toilet", timestamp=1789423200,
                  motion_state="still", fall_detected=True)
)
bathroom_decision = controller.bathroom_decision
# Existing AlertService accepts this already-decided bathroom risk:
# alert_service.handle(bathroom_decision.to_risk_decision())
commands = controller.drain_device_commands()
scenario_actions = controller.drain_scenario_actions()
# Or drain both queues together in timestamp order:
backend_requests = controller.drain_backend_requests()
```

The caller can deliver kitchen and bathroom alerts independently through the
existing AlertService. Water commands never enter the risk-alert path.
Draining the command queue removes delivered commands from memory.

## Morning water

The default `ScenarioConfig.MORNING_WATER_AMOUNT_ML` is 120mL. The representative
backend demo also uses this default without an amount override. Custom amounts remain
supported: the configured value becomes `DeviceCommand.amount_ml`, then
`actions[].amountMl` in the backend request, with `weatherBriefing=true`.
Changing the default affects new commands only; stored pending/sending requests keep
their original amount, body and decision ID. Past `lastDispensedMl` is not rewritten.

ScenarioConfig owns wake-pattern sampling, confirmation times, daily limit, amount,
and UTC offset (default +9). Use Unix timestamps; date/window calculations do not
depend on the machine timezone. A wake in `room` followed by confirmed kitchen entry
is stored once per local date in `wake_times.jsonl`. The most recent
`WAKE_PATTERN_HISTORY_SIZE` records define a median-centered range that includes
the observed spread plus `WAKE_WINDOW_MARGIN_SECONDS`. The range is recalculated
as old records leave the recent-data window. Until `WAKE_PATTERN_MIN_SAMPLES`
exist, `MORNING_START`/`MORNING_END` are used only as a bootstrap range.

Confirmed wake-up requires lying in `room` followed by sitting/standing/walking
for five seconds. Kitchen presence must then last five seconds before the
30-minute wake deadline. Missing activity cannot establish wake-up. Intervening
rooms are allowed. Uncertain samples and gaps at least UNKNOWN_TIMEOUT reset
pending confirmations. Tick alone cannot confirm presence or issue a command.

The water purifier is unavailable by default. Command generation reserves a daily
slot and sets morning_water_dispensed, preventing repeat requests even if the
queue is drained. WATER_DISPENSE_REQUEST means a request was generated; hardware
dispensing/completion is not claimed. Its internal `DeviceCommand` serialization includes
`"event": "water_dispensed"` and `"request_weather_info": true`; this is not the HTTP request schema.
The mapper emits `scenario=water_dispense`, `device=water_purifier`, `action=dispense`,
`amountMl=120` (or the configured amount), and `weatherBriefing=true`.
This module does not fetch or generate weather data. Direct-call daily counters
are in memory and reset on the next input/tick with a different local date.
`IntegrationRuntime` adds a durable outbox reservation before command generation and
restores it after restart; see [backend integration](backend_integration.md).
Device readiness and completion acknowledgements still need an external contract;
`status=idle` describes user activity, not dispensing readiness. Mock tests use an independent
synthetic readiness field; they do not define a real backend field. Unscored rule results use null confidence,
while scored AI results keep their original numeric confidence;
no physical API is called by the scenario itself.

## Bedtime light off

Reliable `room + lying` observations start the bedtime timer. Once
`BEDTIME_LYING_SECONDS` is reached, one `turn_off` request for `light` with `room=room` is
placed in the scenario-action queue. Standing, another room, low confidence, or a
sensor gap resets the pending timer. Continued lying does not generate duplicate
requests; a new lying episode may generate a new request.

## Bathroom fall

The standard location is `toilet`. Existing `BathroomFallScenario`, `bathroom_decision`,
and `bathroom_fall` history/config keys remain compatibility identifiers, not backend scenario enums.
The existing AI scenario owns detection, state transitions and recovery decisions. HTTP integration delegates
caregiver contact, emergency reporting, and device execution to the backend and does **not** send the local
caregiver/report/blink/stove requests described below. The first user alert is handled locally by the
integration runtime through `AlertService` (message generation and WAV synthesis); audio playback remains
the host's responsibility. The runtime accepts an injected `fall_alert_service` to select an LLM/TTS engine;
without one it uses `LLM_PROVIDER` (or the existing fallback message when unset) and `Pyttsx3TTS`.
Fall state transmission, caregiver response ingestion, incident synchronization, and device-action schemas
are unprovided; no guessed endpoint or POST is created. The runtime records AI transitions, including RECOVERED, in the local
`fall_state_changed` audit with measurement time. RECOVERED is not backend incident closure or cancellation of reports.
The unresolved local incident latch continues to guard other automatic commands. A host-supplied, correlated
`safe` caregiver result resolves the local latch; a sensor-only RECOVERED state does not.

An explicit fall event or a fresh standing/walking-to-lying transition starts
FALL_SUSPECTED. Stillness alone never starts an incident. Subsequent continuous
stillness reaches FALL_CONFIRMED at 5 seconds, FALL_WARNING at 10, and
FALL_EMERGENCY at 30. At 60 seconds long_unresponsive is also set. Warning and
emergency map to the existing HIGH alert risk. Recovery requires five seconds
of moving samples without a current explicit fall event.

The same three thresholds create local requests without changing the existing risk decision:
FALL_CONFIRMED requests a user notification/TTS at 5 seconds, FALL_WARNING requests a caregiver
notification at 10 seconds, and FALL_EMERGENCY may request an emergency report at 30 seconds.
The last request is emitted only after the backend reports that the caregiver did not respond:

```python
incident_id = controller.bathroom_decision.incident_id
controller.update_fall_backend_signal(FallBackendSignal(
    timestamp=now, caregiver_status="no_response", incident_id=incident_id,
))
# A confirmed safe response instead ends the incident:
# controller.update_fall_backend_signal(FallBackendSignal(
#     timestamp=now, caregiver_status="safe", incident_id=incident_id,
# ))
```

An integration host passes the same signal to `runtime.receive_fall_backend_signal(signal)`;
the runtime requires a matching incident ID. A `safe` response produces `RESOLVED_BY_CAREGIVER`,
clears the unresolved local guard, and prevents escalation. `no_response` enables the report
request only after the 30-second stillness threshold; it does not claim that a report was sent.
An incident ID persisted in the local outbox can still be closed by a matching `safe` result after restart;
an old `no_response` result cannot recreate a missing stillness history.
The older explicit `allow_emergency_report=True` direct-call gate is retained for compatibility,
but is not accepted by the integration runtime without an explicit caregiver status.

At incident start, a fresh ON stove state adds a `stove` (`room=kitchen`) `turn_off`
request and a `light` (`room=toilet`) `blink` request is always added. Every request is
emitted at most once per incident. These rule-only controls do not call an LLM.

Missing/low-confidence sensing, leaving the bathroom, and stale sensing preserve
the incident severity and interrupt confirmation timers. Tick detects stale
sensing but does not infer continued immobility from silence. New observations
are required for escalation and recovery. The recorded unresponsive duration is
the longest confirmed still interval of the current incident.

Bathroom decisions supply scenario/state/risk context to the LLM, with a separate
system prompt and bathroom-specific fallback messages. Existing TTS error
handling and kitchen prompts are preserved.
