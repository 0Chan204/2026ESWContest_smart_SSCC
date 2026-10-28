"""Real pseudo-USB serial + TCP MQTT tests, and C/Python wire compatibility."""
import asyncio
import ctypes as C
import importlib.util
import json
import os
from pathlib import Path
from unittest import mock
import pty
import random
import struct
import subprocess
import sys
import tempfile
import termios
import tty
import unittest

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "host"))
import gateway as g
import configure_devices as profile


class CFrame(C.Structure):
    _fields_ = [("stream", C.c_uint32), ("size", C.c_uint16), ("type", C.c_uint8),
                ("data", C.c_uint8 * 1024)]


class CParser(C.Structure):
    _fields_ = [("data", C.c_uint8 * 1040), ("used", C.c_size_t)]


class SerialPortTests(unittest.TestCase):
    def test_com_port_uses_requested_baud_without_flow_control(self):
        master, slave = pty.openpty()
        fd = None
        try:
            # Device metadata previously caused the user's 1a86 COM port to be rejected.
            with mock.patch.object(g, "usb_info", return_value={"idVendor": "1a86"}), \
                 mock.patch.object(g.fcntl, "ioctl") as ioctl:
                fd = g.open_serial(os.ttyname(slave), 460800)
                settings = termios.tcgetattr(fd)
                self.assertEqual(settings[4], termios.B460800)
                self.assertEqual(settings[5], termios.B460800)
                self.assertFalse(settings[2] & getattr(termios, "CRTSCTS", 0))
                self.assertFalse(settings[0] & (termios.IXON | termios.IXOFF))
                ioctl.assert_called_once_with(fd, termios.TIOCMBIC,
                    struct.pack("I", termios.TIOCM_DTR | termios.TIOCM_RTS))
        finally:
            for value in (fd, master, slave):
                if value is not None: os.close(value)

    def test_duplicate_gateway_has_clear_error_and_releases_lock(self):
        master, slave = pty.openpty()
        first = second = None
        try:
            path = os.ttyname(slave)
            first = g.open_serial(path)
            with self.assertRaisesRegex(g.PortBusyError, "locked by another program"):
                g.open_serial(path)
            os.close(first); first = None
            second = g.open_serial(path)
        finally:
            for fd in (first, second, master, slave):
                if fd is not None:
                    os.close(fd)


class WireTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        binary = Path(cls.temp.name) / "wire.so"
        subprocess.run(["cc", "-std=c11", "-Wall", "-Wextra", "-Werror", "-shared", "-fPIC",
                        str(PROJECT / "main/gateway_wire.c"), "-o", str(binary)], check=True)
        cls.lib = C.CDLL(str(binary))
        cls.lib.gw_encode.argtypes = [C.c_void_p, C.POINTER(CFrame)]
        cls.lib.gw_encode.restype = C.c_size_t
        cls.callback = C.CFUNCTYPE(None, C.POINTER(CFrame), C.c_void_p)
        cls.lib.gw_feed.argtypes = [C.POINTER(CParser), C.c_void_p, C.c_size_t, cls.callback, C.c_void_p]
        cls.lib.gw_ntp_reply.argtypes = [C.c_void_p, C.c_size_t, C.c_int64, C.c_void_p]
        cls.lib.gw_ntp_reply.restype = C.c_bool

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_c_python_frames_corruption_and_fragmentation(self):
        rng = random.Random(9)
        expected = []
        stream = bytearray(b"boot ROM output\r\n")
        for length in (0, 1, 8, 1024, 511):
            data = rng.randbytes(length)
            frame = g.Frame(g.DATA, 0x10203040 + length, data)
            native = CFrame(stream=frame.stream, size=len(data), type=frame.kind)
            native.data[:len(data)] = data
            out = C.create_string_buffer(1040)
            count = self.lib.gw_encode(out, C.byref(native))
            self.assertEqual(out.raw[:count], frame.encode())
            corrupt = bytearray(frame.encode()); corrupt[12] ^= 0xff
            stream.extend(corrupt)
            stream.extend(frame.encode())
            expected.append(frame)
        # Invalid length and flags cannot overflow either parser.
        stream.extend(g.HEADER.pack(g.MAGIC, g.DATA, 1, 65535, 1, 0))
        stream.extend(g.Frame(g.ACK, 25).encode())
        expected.append(g.Frame(g.ACK, 25))
        actual_c, actual_py = [], []
        parser_c, parser_py = CParser(), g.Parser()
        @self.callback
        def receive(ptr, _):
            f = ptr.contents
            actual_c.append(g.Frame(f.type, f.stream, bytes(f.data[:f.size])))
        offset = 0
        while offset < len(stream):
            count = rng.randint(1, 41)
            data = bytes(stream[offset:offset + count]); offset += count
            self.lib.gw_feed(C.byref(parser_c), data, len(data), receive, None)
            actual_py.extend(parser_py.feed(data))
        self.assertEqual(actual_c, expected)
        self.assertEqual(actual_py, expected)

    def test_local_ntp_time_and_origin(self):
        request = bytearray(48); request[0] = 0x23
        request[40:48] = b"original"
        response = C.create_string_buffer(48)
        timestamp = 1793100000123456
        self.assertTrue(self.lib.gw_ntp_reply(bytes(request), 48, timestamp, response))
        self.assertEqual(response.raw[0], 0x24)
        self.assertEqual(response.raw[1], 2)
        self.assertEqual(response.raw[24:32], b"original")
        seconds, fraction = struct.unpack("!II", response.raw[40:48])
        self.assertAlmostEqual(seconds - 2208988800 + fraction / 2**32, timestamp / 1e6, places=6)
        self.assertFalse(self.lib.gw_ntp_reply(bytes(request), 48, 0, response))
        self.assertFalse(self.lib.gw_ntp_reply(bytes(request), 47, timestamp, response))
        request[0] = 0x24
        self.assertFalse(self.lib.gw_ntp_reply(bytes(request), 48, timestamp, response))

    def test_profile_preserves_pins_credentials_and_client_id(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            original_root, original_gateway = profile.ROOT, profile.GATEWAY
            profile.ROOT = root
            profile.GATEWAY = root / "gateway/esp32s3-gateway"
            try:
                for relative, prefix in profile.PROJECTS.items():
                    project = root / relative; (project / "main").mkdir(parents=True)
                    template = (original_root / relative / "main/Kconfig.projbuild.example").read_text()
                    (project / "main/Kconfig.projbuild.example").write_text(template)
                    (project / "main/Kconfig.projbuild").write_text(template)
                    (project / "sdkconfig").write_text(f'CONFIG_{prefix}_LED_GPIO=18\nCONFIG_{prefix}_MQTT_CLIENT_ID="unique"\nCONFIG_{prefix}_MQTT_PASSWORD="keep"\n')
                (profile.GATEWAY / "main").mkdir(parents=True)
                (profile.GATEWAY / "main/Kconfig.projbuild.example").write_text(
                    (original_gateway / "main/Kconfig.projbuild.example").read_text())
                backup = profile.apply_profile("test-only-password")
                self.assertTrue(backup.is_dir())
                for relative, prefix in profile.PROJECTS.items():
                    project = root / relative
                    text = (project / "sdkconfig").read_text()
                    self.assertIn(f'CONFIG_{prefix}_LED_GPIO=18', text)
                    self.assertIn(f'CONFIG_{prefix}_MQTT_CLIENT_ID="unique"', text)
                    self.assertIn(f'CONFIG_{prefix}_MQTT_PASSWORD="keep"', text)
                    self.assertIn(f'CONFIG_{prefix}_NTP_SERVER="192.168.4.1"', text)
                    self.assertNotIn("test-only-password", (project / "main/Kconfig.projbuild.example").read_text())
                    self.assertTrue((backup / relative / "sdkconfig").exists())
            finally:
                profile.ROOT, profile.GATEWAY = original_root, original_gateway


def packet(kind, body):
    size, encoded = len(body), bytearray()
    while True:
        byte = size % 128; size //= 128
        encoded.append(byte | (0x80 if size else 0))
        if not size:
            return bytes([kind]) + encoded + body


def mqtt_string(text):
    data = text.encode()
    return struct.pack("!H", len(data)) + data


async def read_packet(reader):
    kind = (await reader.readexactly(1))[0]
    size, multiplier = 0, 1
    for _ in range(4):
        b = (await reader.readexactly(1))[0]
        size += (b & 127) * multiplier
        if not b & 128:
            return kind, await reader.readexactly(size)
        multiplier *= 128
    raise ValueError("Invalid MQTT length")


class FakeDevice:
    def __init__(self, wire, stream, credit=True):
        self.wire, self.stream, self.credit = wire, stream, credit
        self.reader = asyncio.StreamReader()
        self.opened, self.closed, self.ack = asyncio.Event(), asyncio.Event(), asyncio.Event()
        self.pending = []

    async def send(self, data):
        for offset in range(0, len(data), 1024):
            self.ack.clear()
            await self.wire.link.send(g.Frame(g.DATA, self.stream, data[offset:offset + 1024]))
            await asyncio.wait_for(self.ack.wait(), 2)


class FakeS3:
    def __init__(self, link):
        self.link, self.devices = link, {}
        self.time_ready = asyncio.Event()

    async def open(self, stream, credit=True):
        dev = FakeDevice(self, stream, credit)
        self.devices[stream] = dev
        await self.link.send(g.Frame(g.OPEN, stream))
        return dev

    async def run(self):
        while True:
            frame = await self.link.receive()
            if frame.kind == g.HELLO:
                for dev in self.devices.values():
                    dev.reader.feed_eof(); dev.closed.set()
                self.devices.clear()
                await self.link.send(g.Frame(g.READY, data=frame.data))
            elif frame.kind == g.TIME:
                self.time_ready.set()
                await self.link.send(g.Frame(g.PONG, data=frame.data))
            elif dev := self.devices.get(frame.stream):
                if frame.kind == g.OPEN_OK:
                    dev.opened.set()
                elif frame.kind == g.ACK:
                    dev.ack.set()
                elif frame.kind == g.CLOSE:
                    dev.reader.feed_eof(); dev.closed.set()
                elif frame.kind == g.DATA:
                    dev.reader.feed_data(frame.data)
                    dev.pending.append(frame.data)
                    if dev.credit:
                        await self.link.send(g.Frame(g.ACK, frame.stream))


class BridgeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.received, self.broker_writers = {}, set()
        self.server = await asyncio.start_server(self.broker, "127.0.0.1", 0)
        self.port = self.server.sockets[0].getsockname()[1]
        self.master, self.slave = pty.openpty()
        for fd in (self.master, self.slave):
            tty.setraw(fd, termios.TCSANOW); os.set_blocking(fd, False)
        self.s3 = FakeS3(g.SerialLink(self.master))
        self.s3_task = asyncio.create_task(self.s3.run())
        self.bridge = g.Bridge(g.SerialLink(self.slave), "127.0.0.1", self.port)
        self.host_task = asyncio.create_task(self.bridge.run())
        await asyncio.wait_for(self.s3.time_ready.wait(), 2)

    async def asyncTearDown(self):
        self.host_task.cancel(); self.s3_task.cancel()
        await asyncio.gather(self.host_task, self.s3_task, return_exceptions=True)
        self.s3.link.close()
        for writer in list(self.broker_writers):
            writer.close()
            await writer.wait_closed()
        self.server.close(); await self.server.wait_closed()
        os.close(self.master); os.close(self.slave)

    async def broker(self, reader, writer):
        self.broker_writers.add(writer)
        try:
            kind, _ = await read_packet(reader)
            self.assertEqual(kind, 0x10)  # CONNECT
            writer.write(b"\x20\x02\x00\x00"); await writer.drain()
            kind, body = await read_packet(reader)
            self.assertEqual(kind, 0x32)  # QoS 1 PUBLISH
            topic_length = int.from_bytes(body[:2], "big")
            pid = body[2 + topic_length:4 + topic_length]
            payload = body[4 + topic_length:]
            message = json.loads(payload)
            self.received[message["device"]] = message
            writer.write(b"\x40\x02" + pid)  # PUBACK
            writer.write(packet(0x32, mqtt_string("home/test/command") + b"\x00\x37" + payload))
            await writer.drain()
            kind, body = await read_packet(reader)
            self.assertEqual((kind, body), (0x40, b"\x00\x37"))
            await reader.read()
        except (asyncio.IncompleteReadError, ConnectionError):
            pass
        finally:
            writer.close()
            await writer.wait_closed()
            self.broker_writers.discard(writer)

    async def exercise(self, stream):
        dev = await self.s3.open(stream)
        await asyncio.wait_for(dev.opened.wait(), 2)
        await dev.send(packet(0x10, b"\x00\x04MQTT\x04\x02\x00\x3c" + mqtt_string(f"device-{stream}")))
        self.assertEqual(await read_packet(dev.reader), (0x20, b"\x00\x00"))
        message = {"device": stream, "value": "정상 상태 " * 400}
        data = json.dumps(message, ensure_ascii=False).encode()
        await dev.send(packet(0x32, mqtt_string("home/test/state") + b"\x00\x29" + data))
        self.assertEqual(await read_packet(dev.reader), (0x40, b"\x00\x29"))
        kind, body = await read_packet(dev.reader)
        self.assertEqual(kind, 0x32)
        self.assertEqual(body, mqtt_string("home/test/command") + b"\x00\x37" + data)
        await dev.send(b"\x40\x02\x00\x37")
        self.assertEqual(self.received[stream], message)
        return dev

    async def test_six_mqtt_connections_qos1_and_commands(self):
        devices = await asyncio.wait_for(asyncio.gather(*(self.exercise(i) for i in range(1, 7))), 8)
        self.assertEqual(len(self.bridge.connections), 6)
        self.assertTrue(all(not d.closed.is_set() for d in devices))
        self.assertGreater(self.bridge.last_pong, 0)

    async def test_slow_client_and_failed_broker_do_not_block_others(self):
        slow = await self.s3.open(1, credit=False)
        await asyncio.wait_for(slow.opened.wait(), 2)
        await slow.send(packet(0x10, b"\x00\x04MQTT\x04\x02\x00\x3c" + mqtt_string("slow")))
        await asyncio.wait_for(slow.reader.readexactly(4), 2)
        good = await asyncio.wait_for(self.exercise(2), 4)
        self.assertFalse(good.closed.is_set())
        self.assertEqual(len(slow.pending), 1)
        # Refuse only a new broker connection, leaving current streams intact.
        self.bridge.port = 0
        failed = await self.s3.open(3)
        await asyncio.wait_for(failed.closed.wait(), 2)
        self.assertFalse(good.closed.is_set())
        self.bridge.port = self.port
        await asyncio.wait_for(self.exercise(4), 4)

    async def test_usb_failure_closes_streams_and_new_session_recovers(self):
        old = await asyncio.wait_for(self.exercise(1), 4)
        self.bridge.link.fail(g.LinkError("test cable removal"))
        with self.assertRaises(g.LinkError):
            await self.host_task
        self.assertFalse(self.bridge.connections)
        self.s3.time_ready.clear()
        self.bridge = g.Bridge(g.SerialLink(self.slave), "127.0.0.1", self.port)
        self.host_task = asyncio.create_task(self.bridge.run())
        await asyncio.wait_for(self.s3.time_ready.wait(), 2)
        self.assertTrue(old.closed.is_set())
        await asyncio.wait_for(self.exercise(1), 4)


if __name__ == "__main__":
    unittest.main()
