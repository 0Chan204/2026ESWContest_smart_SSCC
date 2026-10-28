#!/usr/bin/env python3
"""Apply the private gateway Wi-Fi profile to six appliances and the S3.

Connection credentials are prompted or read from HOMEVIS_AP_PASSWORD, never logged.
Existing files are backed up before editing. GPIO, target and client IDs are preserved.
"""
import argparse
from datetime import datetime, timezone
import getpass
import json
import os
from pathlib import Path
import re
import shutil

ROOT = Path(__file__).resolve().parents[3]
GATEWAY = Path(__file__).resolve().parents[1]
PROJECTS = {
    "kitchen/induction": "INDUCTION",
    "kitchen/kitchen-light": "KL",
    "kitchen/kitchen-light-hood": "KLH",
    "kitchen/water-purifier": "WP",
    "room/room-light": "RL",
    "room/air-purifier": "AP",
}


def kconfig_value(text, key, value):
    pattern = re.compile(r"(^    config " + re.escape(key) + r"\n)(.*?)(?=^    config |^endmenu|\Z)", re.M | re.S)
    def replace(match):
        default = "        default " + json.dumps(value, ensure_ascii=False)
        block, count = re.subn(r'^        default ".*"$', lambda _: default, match[2], count=1, flags=re.M)
        if count != 1:
            raise ValueError(f"Missing string default for {key}")
        return match[1] + block
    result, count = pattern.subn(replace, text)
    if count != 1:
        raise ValueError(f"Missing config {key}")
    return result


def sdkconfig_value(text, key, value):
    line = f"CONFIG_{key}=" + json.dumps(value, ensure_ascii=False)
    result, count = re.subn(r"^CONFIG_" + re.escape(key) + r"=.*$", lambda _: line, text, flags=re.M)
    return result if count else text + "\n" + line + "\n"


def apply_profile(password, ssid="HomeVIS-Devices", broker_host="127.0.0.1"):
    if not 8 <= len(password.encode()) <= 63 or not 1 <= len(ssid.encode()) <= 32:
        raise ValueError("SSID must be 1-32 bytes and WPA2 password 8-63 bytes")
    changes = {}
    for relative, prefix in PROJECTS.items():
        project = ROOT / relative
        public = project / "main/Kconfig.projbuild.example"
        local = project / "main/Kconfig.projbuild"
        settings = {f"{prefix}_WIFI_SSID": ssid,
                    f"{prefix}_MQTT_URI": "mqtt://192.168.4.1:1883",
                    f"{prefix}_NTP_SERVER": "192.168.4.1"}
        public_text = public.read_text()
        local_text = local.read_text() if local.exists() else public_text
        for key, value in settings.items():
            public_text = kconfig_value(public_text, key, value)
            local_text = kconfig_value(local_text, key, value)
        local_text = kconfig_value(local_text, f"{prefix}_WIFI_PASSWORD", password)
        changes[public], changes[local] = public_text, local_text
        sdk = project / "sdkconfig"
        if sdk.exists():
            effective = sdk.read_text()
            for key, value in {**settings, f"{prefix}_WIFI_PASSWORD": password}.items():
                effective = sdkconfig_value(effective, key, value)
            changes[sdk] = effective
    public = GATEWAY / "main/Kconfig.projbuild.example"
    local = GATEWAY / "main/Kconfig.projbuild"
    local_text = local.read_text() if local.exists() else public.read_text()
    local_text = kconfig_value(local_text, "GW_AP_SSID", ssid)
    changes[local] = kconfig_value(local_text, "GW_AP_PASSWORD", password)
    sdk = GATEWAY / "sdkconfig"
    if sdk.exists():
        text = sdkconfig_value(sdk.read_text(), "GW_AP_SSID", ssid)
        changes[sdk] = sdkconfig_value(text, "GW_AP_PASSWORD", password)
    changes[GATEWAY / "host/gateway.local.json"] = json.dumps({
        "serial_port": "/dev/ttyACM0", "serial_baud": 460800, "broker_host": broker_host,
        "broker_port": 1883, "max_streams": 8}, indent=2) + "\n"
    backup = GATEWAY / "host/backups" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    # All parsing is completed before the first change; backups contain private credentials.
    backup.mkdir(parents=True, mode=0o700)
    for path in changes:
        if path.exists():
            saved = backup / path.relative_to(ROOT)
            saved.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, saved)
            saved.chmod(0o600)
    for path, text in changes.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_name(path.name + ".tmp")
        temp.write_text(text)
        if path.name in ("Kconfig.projbuild", "sdkconfig", "gateway.local.json"):
            temp.chmod(0o600)
        temp.replace(path)
    print(f"Updated {len(PROJECTS)} appliances and S3; SSID={ssid}; broker={broker_host}:1883")
    print(f"Private backups: {backup}")
    return backup


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ssid", default="HomeVIS-Devices")
    parser.add_argument("--broker-host", default="127.0.0.1")
    args = parser.parse_args()
    password = os.environ.get("HOMEVIS_AP_PASSWORD") or getpass.getpass("Appliance AP password: ")
    apply_profile(password, args.ssid, args.broker_host)


if __name__ == "__main__":
    main()
