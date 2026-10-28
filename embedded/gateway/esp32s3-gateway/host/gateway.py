#!/usr/bin/env python3
"""Linux/macOS USB -> MQTT TCP gateway. Python 3.10+, standard library only.

This transports TCP bytes, not MQTT publications: IDs, QoS, authentication,
subscriptions and ACKs are preserved by the actual broker and appliance clients.
"""
import argparse
import asyncio
from dataclasses import dataclass
import errno
import fcntl
import glob
import json
import logging
import os
from pathlib import Path
import secrets
import struct
import termios
import time
import tty
import zlib

LOG = logging.getLogger("homevis.gateway")
MAGIC = b"HVU1"
HEADER = struct.Struct("!4sBBHII")
MAX_PAYLOAD = 1024
HELLO, READY, TIME, PONG, OPEN, OPEN_OK, CLOSE, DATA, ACK = range(1, 10)
HEARTBEAT_TIMEOUT = 6
FLOW_TIMEOUT = 10


@dataclass(frozen=True)
class Frame:
    kind: int
    stream: int = 0
    data: bytes = b""

    def encode(self):
        if len(self.data) > MAX_PAYLOAD:
            raise ValueError("Frame exceeds 1024 bytes")
        header = HEADER.pack(MAGIC, self.kind, 0, len(self.data), self.stream, 0)
        crc = zlib.crc32(header[:12] + self.data)
        return header[:12] + struct.pack("!I", crc) + self.data


class Parser:
    def __init__(self):
        self.buffer = bytearray()

    def feed(self, data):
        self.buffer.extend(data)
        frames = []
        while len(self.buffer) >= 4:
            if self.buffer[:4] != MAGIC:
                del self.buffer[0]
                continue
            if len(self.buffer) < HEADER.size:
                break
            _, kind, flags, size, stream, crc = HEADER.unpack_from(self.buffer)
            if flags or size > MAX_PAYLOAD:
                del self.buffer[0]
                continue
            if len(self.buffer) < HEADER.size + size:
                break
            payload = bytes(self.buffer[HEADER.size:HEADER.size + size])
            if zlib.crc32(self.buffer[:12] + payload) != crc:
                del self.buffer[0]
                continue
            frames.append(Frame(kind, stream, payload))
            del self.buffer[:HEADER.size + size]
        return frames


class LinkError(Exception):
    pass


class PortBusyError(LinkError):
    pass


def usb_info(path):
    """Linux USB metadata, also resolving /dev/serial/by-id links."""
    device = Path("/sys/class/tty") / Path(os.path.realpath(path)).name / "device"
    for parent in device.resolve().parents:
        if not (parent / "idVendor").exists():
            continue
        result = {}
        for key in ("idVendor", "idProduct", "manufacturer", "product", "serial"):
            try:
                result[key] = (parent / key).read_text().strip()
            except OSError:
                pass
        return result
    return {}


def list_ports():
    aliases = {}
    for path in sorted(glob.glob("/dev/serial/by-id/*")):
        aliases.setdefault(os.path.realpath(path), []).append(path)
    ports = sorted(set(glob.glob("/dev/ttyACM*") + glob.glob("/dev/ttyUSB*") + glob.glob("/dev/cu.*")))
    for path in ports:
        info = usb_info(path)
        description = " ".join(info.get(key, "") for key in ("manufacturer", "product", "serial")).strip()
        print(f"{path}: {description or 'USB identity unavailable'}")
        for alias in aliases.get(os.path.realpath(path), []):
            print(f"  {alias}")
    if not ports:
        print("No serial ports found. Connect the S3 COM port (default firmware) or configured native USB port.")


class SerialLink:
    def __init__(self, fd):
        self.fd = fd
        self.loop = asyncio.get_running_loop()
        self.frames = asyncio.Queue(maxsize=64)
        self.parser = Parser()
        self.lock = asyncio.Lock()
        self.error = None
        self.closed = False
        self.loop.add_reader(fd, self._read)

    def fail(self, error):
        if self.error is not None:
            return
        self.error = error
        self.loop.remove_reader(self.fd)
        # Wake the receiver even if an overflow caused this failure.
        while not self.frames.empty():
            self.frames.get_nowait()
        self.frames.put_nowait(None)

    def _read(self):
        try:
            data = os.read(self.fd, 8192)
            if not data:
                raise LinkError("USB disconnected")
            for frame in self.parser.feed(data):
                self.frames.put_nowait(frame)
        except BlockingIOError:
            pass
        except (OSError, LinkError, asyncio.QueueFull) as error:
            self.fail(LinkError(f"USB receive failed: {error}"))

    async def receive(self):
        if self.error:
            raise self.error
        frame = await self.frames.get()
        if self.error or frame is None:
            raise self.error or LinkError("USB session ended")
        return frame

    async def _writable(self):
        ready = self.loop.create_future()
        def wake():
            if not ready.done():
                ready.set_result(None)
        self.loop.add_writer(self.fd, wake)
        try:
            await ready
        finally:
            self.loop.remove_writer(self.fd)

    async def _send(self, data):
        async with self.lock:
            view = memoryview(data)
            while view:
                if self.error or self.closed:
                    raise self.error or LinkError("USB session closed")
                try:
                    n = os.write(self.fd, view)
                    if n == 0:
                        raise LinkError("USB write returned zero")
                    view = view[n:]
                except BlockingIOError:
                    await self._writable()

    async def send(self, frame):
        try:
            await asyncio.wait_for(self._send(frame.encode()), timeout=2)
        except (OSError, asyncio.TimeoutError, LinkError) as error:
            failure = LinkError(f"USB transmit failed: {error}")
            self.fail(failure)
            raise failure from error

    def close(self):
        self.closed = True
        self.loop.remove_reader(self.fd)
        self.loop.remove_writer(self.fd)


class Connection:
    def __init__(self, bridge, stream):
        self.bridge, self.stream = bridge, stream
        self.writer = None
        self.ack = asyncio.Event()
        self.ack.set()
        self.awaiting_ack = False
        self.writing = False
        self.closed = False
        self.tasks = set()

    def spawn(self, coroutine):
        task = self.bridge.spawn(coroutine)
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)

    def close(self, notify=True):
        if self.closed:
            return
        self.closed = True
        self.bridge.connections.pop(self.stream, None)
        current = asyncio.current_task()
        for task in list(self.tasks):
            if task is not current:
                task.cancel()
        if self.writer:
            self.writer.close()
        if notify:
            self.bridge.spawn(self.bridge.link.send(Frame(CLOSE, self.stream)))
        LOG.info("stream %d closed", self.stream)

    async def connect(self):
        try:
            reader, writer = await asyncio.wait_for(asyncio.open_connection(
                self.bridge.host, self.bridge.port), 4)
            self.writer = writer
            if self.closed:
                writer.close()
                return
            await self.bridge.link.send(Frame(OPEN_OK, self.stream))
            LOG.info("stream %d connected to broker %s:%d", self.stream, self.bridge.host, self.bridge.port)
            await self.read_broker(reader)
        except (OSError, asyncio.TimeoutError) as error:
            LOG.warning("stream %d broker connection failed: %s", self.stream, error)
            self.close()

    async def read_broker(self, reader):
        try:
            while not self.closed:
                await asyncio.wait_for(self.ack.wait(), FLOW_TIMEOUT)
                data = await reader.read(MAX_PAYLOAD)
                if not data:
                    break
                self.ack.clear()
                self.awaiting_ack = True
                await self.bridge.link.send(Frame(DATA, self.stream, data))
        except (OSError, asyncio.TimeoutError) as error:
            LOG.warning("stream %d broker read/flow timeout: %s", self.stream, error)
        finally:
            self.close()

    async def write_broker(self, data):
        self.writing = True
        try:
            self.writer.write(data)
            await asyncio.wait_for(self.writer.drain(), FLOW_TIMEOUT)
            await self.bridge.link.send(Frame(ACK, self.stream))
        except (OSError, asyncio.TimeoutError) as error:
            LOG.warning("stream %d broker write failed: %s", self.stream, error)
            self.close()
        finally:
            self.writing = False


class Bridge:
    def __init__(self, link, host, port=1883, max_streams=8):
        self.link, self.host, self.port = link, host, port
        self.max_streams = max_streams
        self.connections = {}
        self.tasks = set()
        self.last_pong = 0
        self.stopping = False

    def spawn(self, coroutine):
        task = asyncio.create_task(coroutine)
        self.tasks.add(task)
        def done(task):
            self.tasks.discard(task)
            if not task.cancelled() and (error := task.exception()) is not None and not self.stopping:
                self.link.fail(LinkError(f"Bridge task failed: {error}"))
        task.add_done_callback(done)
        return task

    async def heartbeat(self):
        while True:
            if time.monotonic() - self.last_pong > HEARTBEAT_TIMEOUT:
                raise LinkError("S3 heartbeat timed out; resetting all streams")
            await self.link.send(Frame(TIME, data=struct.pack("!Q", time.time_ns() // 1_000_000)))
            await asyncio.sleep(1)

    async def handshake(self):
        nonce = secrets.token_bytes(8)
        for _ in range(6):
            await self.link.send(Frame(HELLO, data=nonce))
            deadline = time.monotonic() + 1
            while time.monotonic() < deadline:
                try:
                    frame = await asyncio.wait_for(self.link.receive(), deadline - time.monotonic())
                except asyncio.TimeoutError:
                    break
                if frame == Frame(READY, data=nonce):
                    self.last_pong = time.monotonic()
                    LOG.info("S3 handshake ready; supplying laptop time")
                    return
        raise LinkError("S3 did not answer: check firmware transport (default COM/UART0), --baud and --list-ports")

    async def run(self):
        try:
            await self.handshake()
            self.spawn(self.heartbeat())
            while True:
                frame = await self.link.receive()
                if frame.kind == PONG and frame.stream == 0 and len(frame.data) == 8:
                    self.last_pong = time.monotonic()
                    continue
                if frame.kind == READY:
                    continue  # Duplicate READY from handshake retries.
                if frame.kind == OPEN and frame.stream and not frame.data:
                    if frame.stream in self.connections:
                        continue
                    if len(self.connections) >= self.max_streams:
                        await self.link.send(Frame(CLOSE, frame.stream))
                        continue
                    conn = Connection(self, frame.stream)
                    self.connections[frame.stream] = conn
                    conn.spawn(conn.connect())
                    continue
                conn = self.connections.get(frame.stream)
                if not conn:
                    continue
                if frame.kind == CLOSE and not frame.data:
                    conn.close(notify=False)
                elif frame.kind == ACK and not frame.data and conn.awaiting_ack:
                    conn.awaiting_ack = False
                    conn.ack.set()
                elif frame.kind == DATA and frame.data and conn.writer and not conn.writing:
                    # Reserve synchronously: a second queued DATA must not race this task.
                    conn.writing = True
                    conn.spawn(conn.write_broker(frame.data))
                else:
                    conn.close()
        finally:
            self.stopping = True
            for conn in list(self.connections.values()):
                conn.close(notify=False)
            tasks = list(self.tasks)
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            self.link.close()


def open_serial(path, baud=460800):
    info = usb_info(path)
    speed = getattr(termios, f"B{baud}", None)
    if speed is None:
        raise ValueError(f"Unsupported serial baud rate: {baud}")
    try:
        fd = os.open(path, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
    except OSError as error:
        if error.errno in (errno.EAGAIN, errno.EBUSY):
            raise PortBusyError(f"Serial port {path} is busy; stop the other gateway/serial monitor first") from error
        raise
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise PortBusyError(f"Serial port {path} is locked by another program; stop duplicate gateways/serial monitors") from error
        tty.setraw(fd, termios.TCSANOW)
        settings = termios.tcgetattr(fd)
        settings[4] = settings[5] = speed  # Must match UART0 firmware; native USB ignores baud.
        settings[2] &= ~(getattr(termios, "CRTSCTS", 0) | termios.CSTOPB | termios.PARENB)
        settings[2] |= termios.CLOCAL | termios.CREAD
        settings[0] &= ~(termios.IXON | termios.IXOFF | getattr(termios, "IXANY", 0))
        settings[6][termios.VMIN] = 1
        settings[6][termios.VTIME] = 0
        termios.tcsetattr(fd, termios.TCSANOW, settings)
        if info.get("idVendor", "").lower() in {"10c4", "1a86", "0403", "067b"}:
            # Release ESP auto-reset/download lines on USB-UART adapters.
            fcntl.ioctl(fd, termios.TIOCMBIC, struct.pack("I", termios.TIOCM_DTR | termios.TIOCM_RTS))
        termios.tcflush(fd, termios.TCIOFLUSH)
        return fd
    except BaseException:
        os.close(fd)
        raise


async def serve(args):
    while True:
        fd = None
        try:
            fd = open_serial(args.port, args.baud)
            LOG.info("Serial %s @ %d -> MQTT %s:%d", args.port, args.baud, args.broker_host, args.broker_port)
            await Bridge(SerialLink(fd), args.broker_host, args.broker_port, args.max_streams).run()
        except PortBusyError as error:
            LOG.error("%s. Exiting to avoid competing for the USB port.", error)
            return
        except (OSError, LinkError) as error:
            LOG.warning("%s; reconnecting in 2 seconds", error)
            if isinstance(error, OSError) and error.errno == errno.EACCES:
                LOG.error("Serial permission denied: check dialout group membership and re-login")
        finally:
            if fd is not None:
                os.close(fd)
        await asyncio.sleep(2)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path(__file__).with_name("gateway.local.json"))
    parser.add_argument("--list-ports", action="store_true", help="Show serial ports and stable USB device paths without opening them")
    parser.add_argument("--port", help="Board COM/native USB port, preferably /dev/serial/by-id/...")
    parser.add_argument("--baud", type=int, help="Serial baud rate, default 460800; match GW_SERIAL_BAUD")
    parser.add_argument("--broker-host")
    parser.add_argument("--broker-port", type=int)
    parser.add_argument("--max-streams", type=int)
    args = parser.parse_args()
    if args.list_ports:
        list_ports()
        return
    try:
        config = json.loads(args.config.read_text()) if args.config.exists() else {}
    except (ValueError, OSError) as error:
        parser.error(f"Cannot read configuration: {error}")
    args.port = args.port or config.get("serial_port", "/dev/ttyACM0")
    args.broker_host = args.broker_host or config.get("broker_host", "127.0.0.1")
    args.broker_port = args.broker_port or config.get("broker_port", 1883)
    args.max_streams = args.max_streams or config.get("max_streams", 8)
    args.baud = args.baud or config.get("serial_baud", 460800)
    if not isinstance(args.baud, int) or getattr(termios, f"B{args.baud}", None) is None:
        parser.error("Unsupported serial baud rate")
    if not isinstance(args.broker_port, int) or not 1 <= args.broker_port <= 65535:
        parser.error("broker_port must be 1..65535")
    if not isinstance(args.max_streams, int) or not 1 <= args.max_streams <= 10:
        parser.error("max_streams must be 1..10")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        asyncio.run(serve(args))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
