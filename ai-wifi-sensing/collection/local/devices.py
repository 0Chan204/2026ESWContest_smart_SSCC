"""Discover USB serial devices and keep ESP names stable across reconnects."""
import copy
from pathlib import Path
import re

from serial.tools import list_ports

from csi_capture.server import atomic_write, identifier
import json


def natural_key(value):
    return [int(part) if part.isdigit() else part for part in re.split(r"(\d+)", value)]


def port_identity(info):
    if info.serial_number:
        return f"usb:{info.vid}:{info.pid}:{info.serial_number}:{getattr(info, 'interface', '')}"
    if info.location:
        return f"location:{info.vid}:{info.pid}:{info.location}"
    return f"port:{info.device}"


def stable_path(port, directory=Path("/dev/serial/by-id")):
    path = Path(port)
    if not path.exists():
        return str(path)
    for candidate in sorted(directory.glob("*")):
        try:
            if candidate.resolve(strict=True) == path.resolve(strict=True):
                return str(candidate)
        except OSError:
            continue
    return str(path.resolve())


class DeviceRegistry:
    def __init__(self, path, devices=None, baud=115200, provider=None):
        self.path = Path(path)
        self.configured = copy.deepcopy(devices)
        self.baud = baud
        self.provider = provider or list_ports.comports
        self.bindings = json.loads(self.path.read_text()) if self.path.exists() else {}
        self.devices = []
        if devices is not None:
            seen = set()
            for device in devices:
                identifier(device["id"])
                if device["id"] in seen or not device.get("port"):
                    raise ValueError("ESP32 이름은 중복될 수 없으며 각 USB 포트가 필요합니다.")
                seen.add(device["id"])

    def refresh(self):
        infos = sorted(self.provider(), key=lambda info: natural_key(info.device))
        usb = [info for info in infos if info.vid is not None
               or info.device.startswith(("/dev/ttyACM", "/dev/ttyUSB"))]
        by_identity = {port_identity(info): info for info in infos}
        by_port = {info.device: info for info in infos}
        changed = False
        devices = []
        if self.configured is None:
            for info in usb:
                identity = port_identity(info)
                if not any(binding.get("identity") == identity for binding in self.bindings.values()):
                    index = 1
                    while f"esp-{index:02d}" in self.bindings:
                        index += 1
                    self.bindings[f"esp-{index:02d}"] = {"identity": identity}
                    changed = True
            for name, binding in sorted(self.bindings.items(), key=lambda pair: natural_key(pair[0])):
                if not binding.get("identity"):
                    continue
                info = by_identity.get(binding["identity"])
                if info:
                    new = {**binding, "port": info.device, "open_port": stable_path(info.device)}
                    if new != binding:
                        self.bindings[name] = new
                        changed = True
                    binding = new
                devices.append({"id": name, "port": binding.get("port", ""),
                                "open_port": binding.get("open_port", binding.get("port", "")),
                                "baud": self.baud, "target_mac": "", "online": info is not None})
        else:
            for configured in self.configured:
                name, port = configured["id"], configured["port"]
                binding = self.bindings.get(name, {})
                if binding.get("configured_port") == port:
                    if "identity" in binding:
                        info = by_identity.get(binding["identity"])
                        current = info.device if info else binding.get("port", port)
                        opening = stable_path(current) if info else binding.get("open_port", current)
                        online = info is not None
                    else:
                        current = port
                        opening = binding.get("open_port", stable_path(port))
                        online = Path(opening).exists()
                else:
                    info = by_port.get(port)
                    current, opening, online = port, stable_path(port), info is not None or Path(port).exists()
                new = {"configured_port": port, "port": current, "open_port": opening}
                if binding.get("configured_port") == port and binding.get("identity"):
                    new["identity"] = binding["identity"]
                elif by_port.get(port):
                    new["identity"] = port_identity(by_port[port])
                if new != binding:
                    self.bindings[name] = new
                    changed = True
                devices.append({**configured, "port": current, "open_port": opening,
                                "baud": configured.get("baud", self.baud),
                                "target_mac": configured.get("target_mac", ""), "online": online})
        opening_ports = [device["open_port"] for device in devices if device["online"]]
        if len(opening_ports) != len(set(opening_ports)):
            raise ValueError("동일한 USB 포트가 두 ESP32에 등록되어 있습니다.")
        if changed:
            atomic_write(self.path, json.dumps(self.bindings, indent=2).encode())
        self.devices = devices
        return copy.deepcopy(devices)
