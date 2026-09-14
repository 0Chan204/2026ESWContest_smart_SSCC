# Additional central-controller scenarios

`CentralController.update_sensing`, `update_appliance`, and `tick` continue to
return the existing kitchen `RealtimeDecision`. New results are separate:

```python
from src.control import CentralController, ScenarioConfig, SensingUpdate

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
```

The caller can deliver kitchen and bathroom alerts independently through the
existing AlertService. Water commands never enter the risk-alert path.
Draining the command queue removes delivered commands from memory.

## Morning water

ScenarioConfig owns the morning window, confirmation times, daily limit, amount,
and UTC offset (default +9). Use Unix timestamps; date/window calculations do not
depend on the machine timezone. The window is start-inclusive and end-exclusive.
Confirmed wake-up requires bedroom lying followed by sitting/standing/walking
for five seconds. Kitchen presence must then last five seconds before the
30-minute wake deadline. Missing activity cannot establish wake-up. Intervening
rooms are allowed. Uncertain samples and gaps at least UNKNOWN_TIMEOUT reset
pending confirmations. Tick alone cannot confirm presence or issue a command.

The dispenser is unavailable by default. Command generation reserves a daily
slot and sets morning_water_dispensed, preventing repeat requests even if the
queue is drained. WATER_DISPENSE_REQUEST means a request was generated; hardware
dispensing/completion is not claimed. Daily counters are in memory and reset on
the next input/tick with a different local date. Production integration needs a
durable daily ledger across process restarts, device readiness, command delivery
and completion acknowledgements; no physical API is called here.

## Bathroom fall

An explicit fall event or a fresh standing/walking-to-lying transition starts
FALL_SUSPECTED. Stillness alone never starts an incident. Subsequent continuous
stillness reaches FALL_CONFIRMED at 5 seconds, FALL_WARNING at 10, and
FALL_EMERGENCY at 30. At 60 seconds long_unresponsive is also set. Warning and
emergency map to the existing HIGH alert risk. Recovery requires five seconds
of moving samples without a current explicit fall event.

Missing/low-confidence sensing, leaving the bathroom, and stale sensing preserve
the incident severity and interrupt confirmation timers. Tick detects stale
sensing but does not infer continued immobility from silence. New observations
are required for escalation and recovery. The recorded unresponsive duration is
the longest confirmed still interval of the current incident.

Bathroom decisions supply scenario/state/risk context to the LLM, with a separate
system prompt and bathroom-specific fallback messages. Existing TTS error
handling and kitchen prompts are preserved.
