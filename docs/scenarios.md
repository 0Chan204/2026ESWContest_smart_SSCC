# Additional central-controller scenarios

`CentralController.update_sensing`, `update_appliance`, and `tick` continue to
return the existing kitchen `RealtimeDecision`. New results are separate:

```python
from src.control import (
    CentralController, FallBackendSignal, ScenarioConfig, SensingUpdate,
)

controller = CentralController(
    scenario_config=ScenarioConfig(),
    water_dispenser_available=True,  # Set only after checking device readiness.
)
kitchen_decision = controller.update_sensing(
    SensingUpdate("bathroom", timestamp=1789423200,
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

ScenarioConfig owns wake-pattern sampling, confirmation times, daily limit, amount,
and UTC offset (default +9). Use Unix timestamps; date/window calculations do not
depend on the machine timezone. A bedroom wake followed by confirmed kitchen entry
is stored once per local date in `wake_times.jsonl`. The most recent
`WAKE_PATTERN_HISTORY_SIZE` records define a median-centered range that includes
the observed spread plus `WAKE_WINDOW_MARGIN_SECONDS`. The range is recalculated
as old records leave the recent-data window. Until `WAKE_PATTERN_MIN_SAMPLES`
exist, `MORNING_START`/`MORNING_END` are used only as a bootstrap range.

Confirmed wake-up requires bedroom lying followed by sitting/standing/walking
for five seconds. Kitchen presence must then last five seconds before the
30-minute wake deadline. Missing activity cannot establish wake-up. Intervening
rooms are allowed. Uncertain samples and gaps at least UNKNOWN_TIMEOUT reset
pending confirmations. Tick alone cannot confirm presence or issue a command.

The dispenser is unavailable by default. Command generation reserves a daily
slot and sets morning_water_dispensed, preventing repeat requests even if the
queue is drained. WATER_DISPENSE_REQUEST means a request was generated; hardware
dispensing/completion is not claimed. Its serialized payload always includes
`"event": "water_dispensed"` and `"request_weather_info": true`; this is only a
backend signal and this module does not fetch or generate weather data. Daily counters are in memory and reset on
the next input/tick with a different local date. Production integration needs a
durable daily ledger across process restarts, device readiness, command delivery
and completion acknowledgements; no physical API is called here.

## Bedtime light off

Reliable `bedroom + lying` observations start the bedtime timer. Once
`BEDTIME_LYING_SECONDS` is reached, one `turn_off` request for `bedroom_light` is
placed in the scenario-action queue. Standing, another room, low confidence, or a
sensor gap resets the pending timer. Continued lying does not generate duplicate
requests; a new lying episode may generate a new request.

## Bathroom fall

An explicit fall event or a fresh standing/walking-to-lying transition starts
FALL_SUSPECTED. Stillness alone never starts an incident. Subsequent continuous
stillness reaches FALL_CONFIRMED at 5 seconds, FALL_WARNING at 10, and
FALL_EMERGENCY at 30. At 60 seconds long_unresponsive is also set. Warning and
emergency map to the existing HIGH alert risk. Recovery requires five seconds
of moving samples without a current explicit fall event.

The same three thresholds drive backend requests without changing the existing
risk decision: FALL_CONFIRMED requests a user notification, FALL_WARNING requests
a caregiver notification, and FALL_EMERGENCY may request an emergency report.
The last request is emitted only after the backend supplies an explicit gate:

```python
controller.update_fall_backend_signal(
    FallBackendSignal(timestamp=now, allow_emergency_report=True)
)
requests = controller.drain_scenario_actions()
```

At incident start, a fresh ON induction state adds an induction `turn_off`
request and a bathroom-light `blink` request is always added. Every request is
emitted at most once per incident. These rule-only controls do not call an LLM.

Missing/low-confidence sensing, leaving the bathroom, and stale sensing preserve
the incident severity and interrupt confirmation timers. Tick detects stale
sensing but does not infer continued immobility from silence. New observations
are required for escalation and recovery. The recorded unresponsive duration is
the longest confirmed still interval of the current incident.

Bathroom decisions supply scenario/state/risk context to the LLM, with a separate
system prompt and bathroom-specific fallback messages. Existing TTS error
handling and kitchen prompts are preserved.
