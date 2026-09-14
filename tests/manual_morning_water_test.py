from datetime import datetime, timedelta, timezone

from src.control import CentralController, SensingUpdate
from src.llm.factory import create_llm
from src.llm.message_generator import LLMMessageGenerator


def main() -> None:
    print("Qwen3-8B 로딩 중...")
    generator = LLMMessageGenerator(create_llm("qwen"))
    controller = CentralController(water_dispenser_available=True)
    kst = timezone(timedelta(hours=9))
    base = datetime(2026, 9, 15, 7, 0, 0, tzinfo=kst).timestamp()

    samples = (
        SensingUpdate("bedroom", base, activity="lying"),
        SensingUpdate("bedroom", base + 1, activity="standing"),
        SensingUpdate("bedroom", base + 6, activity="standing"),
        SensingUpdate("living_room", base + 7, activity="walking"),
        SensingUpdate("kitchen", base + 8, activity="standing"),
        SensingUpdate("kitchen", base + 13, activity="standing"),
    )
    for sample in samples:
        controller.update_sensing(sample)

    commands = controller.drain_device_commands()
    if not commands:
        raise RuntimeError("Morning water scenario did not create a device command")
    command = commands[0]
    result = generator.generate_device_command(command)

    print("\n=== Morning Water State ===")
    print("state:", controller.morning_water.state.value)
    print("\n=== Device Command ===")
    print("command_type:", command.command_type)
    print("device:", command.device)
    print("amount_ml:", command.amount_ml)
    print("water_temperature:", command.water_temperature)
    print("\n=== Qwen3-8B Output ===")
    print(result.message)
    print("\nLLM:", result.llm_name)
    print("fallback:", result.fallback_used)
    if result.error:
        print("error:", result.error)


if __name__ == "__main__":
    main()
