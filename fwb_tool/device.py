"""
device.py - request/response layer over a transport.

Device owns the frame parser, matches responses to requests (cmd | 0x80),
routes unsolicited telemetry frames to a callback, and loads firmware
images (.bin / Intel .hex) for OTA.
"""
from __future__ import annotations

import queue
import threading
import time
from dataclasses import dataclass

from .protocol import (
    Frame, FrameParser, build_frame,
    APP_TELEMETRY_REPORT,
    PROTO_OK,
)
from .transport import SerialTransport, BleTransport

DEFAULT_TIMEOUT = 1.5


class DeviceError(RuntimeError):
    pass


@dataclass
class Telemetry:
    uptime_ms: int
    vbat_mv: int
    flags: int

    @property
    def pwm_active(self) -> bool:
        return bool(self.flags & 0x01)


class Device:
    """One connected workbench device (either transport)."""

    def __init__(self, transport, on_telemetry=None):
        self.transport = transport
        self.parser = FrameParser()
        self.frames: queue.Queue[Frame] = queue.Queue()
        self.on_telemetry = on_telemetry
        self._rx_lock = threading.Lock()
        self._tx_lock = threading.Lock()
        # transports push raw bytes into _on_rx
        self.transport.on_rx = self._on_rx

    # ---- lifecycle ----
    @classmethod
    def open_serial(cls, port: str, baud: int = 115200, on_telemetry=None) -> "Device":
        t = SerialTransport(port, baud)
        t.open()
        return cls(t, on_telemetry)

    @classmethod
    def open_ble(cls, address: str, on_telemetry=None) -> "Device":
        t = BleTransport(address)
        t.open()
        return cls(t, on_telemetry)

    def close(self) -> None:
        self.transport.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    # ---- rx plumbing ----
    def _on_rx(self, data: bytes) -> None:
        with self._rx_lock:
            frames = list(self.parser.feed(data))
        for f in frames:
            if f.cmd == APP_TELEMETRY_REPORT:
                if self.on_telemetry:
                    self.on_telemetry(parse_telemetry(f.payload))
            else:
                self.frames.put(f)

    # ---- request/response ----
    def request(self, cmd: int, payload: bytes = b"", timeout: float = DEFAULT_TIMEOUT,
                retries: int = 1) -> Frame:
        """Send a command, wait for its (cmd|0x80) response."""
        expect = cmd | 0x80
        last_exc: Exception | None = None
        for attempt in range(retries + 1):
            # drain stale responses first
            while True:
                try:
                    self.frames.get_nowait()
                except queue.Empty:
                    break
            frame_tx = build_frame(cmd, payload)
            with self._tx_lock:
                self.transport.write(frame_tx)
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                try:
                    f = self.frames.get(timeout=0.1)
                except queue.Empty:
                    continue
                if f.cmd == expect:
                    return f
                # unsolicited/other frame: keep waiting
            last_exc = DeviceError(f"timeout waiting for response to cmd=0x{cmd:02X}")
        raise last_exc  # type: ignore[misc]

    def request_ok(self, cmd: int, payload: bytes = b"", timeout: float = DEFAULT_TIMEOUT,
                   retries: int = 1) -> Frame:
        f = self.request(cmd, payload, timeout, retries)
        if f.status != PROTO_OK:
            from .protocol import ERR_NAMES
            raise DeviceError(
                f"cmd 0x{cmd:02X} failed: {ERR_NAMES.get(f.status, hex(f.status))}")
        return f

    # ---- convenience ops ----
    def ping(self) -> None:
        self.request_ok(0x10)

    def get_version(self):
        """Returns ((bl_major,bl_minor,bl_patch),(app_major,app_minor,app_patch))."""
        from .protocol import APP_GET_VERSION
        f = self.request_ok(APP_GET_VERSION)
        p = f.payload
        return tuple(p[1:4]), tuple(p[4:7])

    def read_telemetry(self, timeout: float = DEFAULT_TIMEOUT) -> Telemetry:
        """Fetch one telemetry report (GET_TELEMETRY responds with 0x9A)."""
        from .protocol import APP_GET_TELEMETRY
        # send request; the 0x9A frame lands in on_telemetry -- so capture it there
        holder: queue.Queue[Telemetry] = queue.Queue(maxsize=1)

        def _cap(t: Telemetry) -> None:
            try:
                holder.put_nowait(t)
            except queue.Full:
                pass

        prev = self.on_telemetry
        self.on_telemetry = _cap
        try:
            self.transport.write(build_frame(APP_GET_TELEMETRY))
            return holder.get(timeout=timeout)
        finally:
            self.on_telemetry = prev


def parse_telemetry(payload: bytes) -> Telemetry:
    if len(payload) < 7:
        raise DeviceError("short telemetry frame")
    up = int.from_bytes(payload[0:4], "big")
    mv = int.from_bytes(payload[4:6], "big")
    return Telemetry(uptime_ms=up, vbat_mv=mv, flags=payload[6])


# ---------------- firmware image loading ----------------

def load_image(path: str, app_base: int = 0x08003000, app_max: int = 0x1CC00) -> bytes:
    """Load a .bin or Intel .hex firmware image, extracted from app_base.

    .hex: records are merged; the contiguous block starting at app_base is
    returned. .bin: returned as-is (assumed to be linked at app_base).

    app_max defaults to the largest possible app region (128KB layout). The
    bootloader's BL_QUERY reports the real limit (51KB on a 64KB part) and
    ota_update() rejects an image that does not fit."""
    data = open(path, "rb").read()
    if path.lower().endswith(".hex") or (not path.lower().endswith(".bin")
                                         and data[:1] == b":"):
        return _load_ihex(data, app_base, app_max)
    if len(data) > app_max:
        raise DeviceError(f"image {len(data)}B exceeds app partition {app_max}B")
    return data


def _load_ihex(data: bytes, app_base: int, app_max: int) -> bytes:
    mem: dict[int, int] = {}
    ext_base = 0
    for line in data.decode("ascii", errors="ignore").splitlines():
        line = line.strip()
        if not line.startswith(":"):
            continue
        raw = bytes.fromhex(line[1:])
        count, addr_hi, addr_lo, rtype = raw[0], raw[1], raw[2], raw[3]
        payload = raw[4:4 + count]
        if rtype == 0x00:                      # data
            base = ext_base + (addr_hi << 8) + addr_lo
            for i, b in enumerate(payload):
                mem[base + i] = b
        elif rtype == 0x04:                    # extended linear address
            ext_base = int.from_bytes(payload, "big") << 16
        elif rtype in (0x01, 0x05):            # EOF / start address
            continue
    if not mem:
        raise DeviceError("empty Intel HEX file")
    lo = min(mem)
    hi = max(mem)
    # trim to the app region (hex files may include config-page records)
    region = {a: v for a, v in mem.items() if app_base <= a < app_base + app_max}
    if not region:
        raise DeviceError(f"no records inside app region 0x{app_base:08X}..")
    out = bytearray(max(region) - app_base + 1)
    for a, v in region.items():
        out[a - app_base] = v
    if len(out) > app_max:
        raise DeviceError("image exceeds app partition")
    return bytes(out)
