"""
transport.py - byte-pipe transports (serial / BLE) behind one interface.

A transport is just: open(), close(), write(bytes), and a callback that
receives inbound bytes. The Device layer owns framing; transports stay dumb
so serial and BLE are fully interchangeable (same protocol over any pipe).
"""
from __future__ import annotations

import threading
from typing import Callable


class TransportError(RuntimeError):
    pass


class SerialTransport:
    """pyserial pipe: USB-TTL adapter, or a BLE module exposed as a COM port."""

    def __init__(self, port: str, baud: int = 115200, on_rx: Callable[[bytes], None] = lambda d: None):
        self.port = port
        self.baud = baud
        self.on_rx = on_rx
        self._ser = None
        self._thread: threading.Thread | None = None
        self._closing = False

    def open(self) -> None:
        import serial  # deferred import: only serial users need pyserial
        try:
            self._ser = serial.Serial(self.port, self.baud, timeout=0.05)
        except Exception as e:  # noqa: BLE001 - surface a readable error
            raise TransportError(f"cannot open {self.port}: {e}") from e
        self._closing = False
        self._thread = threading.Thread(target=self._reader, daemon=True)
        self._thread.start()

    def _reader(self) -> None:
        while not self._closing:
            try:
                data = self._ser.read(256)
            except Exception:  # port closed under us
                return
            if data:
                self.on_rx(data)

    def write(self, data: bytes) -> None:
        if self._ser is None:
            raise TransportError("transport not open")
        self._ser.write(data)

    def close(self) -> None:
        self._closing = True
        if self._ser is not None:
            try:
                self._ser.close()
            except Exception:
                pass
            self._ser = None

    def __enter__(self):
        self.open()
        return self

    def __exit__(self, *exc):
        self.close()


class BleTransport:
    """BLE GATT pipe for transparent-bridge modules (ECB02H / JDY / HC-08...).

    Connects via BlueZ (Linux) or WinRT (Windows) using bleak. Discovers the
    write and notify characteristics automatically, preferring the common
    transparent-bridge UUIDs (FFE0/FFE1, FFF0/FFF1, FFB0/FFB1) and falling
    back to any write/notify pair. MTU-safe writes (chunk to 182 bytes).
    """

    # Well-known transparent-BLE services first, then generic discovery.
    PREFERRED = ("0000ffe1-0000-1000-8000-00805f9b34fb",
                 "0000fff1-0000-1000-8000-00805f9b34fb",
                 "0000ffb1-0000-1000-8000-00805f9b34fb",
                 "00002af1-0000-1000-8000-00805f9b34fb")

    def __init__(self, address: str, on_rx: Callable[[bytes], None] = lambda d: None,
                 timeout: float = 10.0):
        self.address = address
        self.on_rx = on_rx
        self.timeout = timeout
        self._loop = None
        self._thread: threading.Thread | None = None
        self._client = None
        self._write_char = None
        self._closing = False

    # ---- background asyncio loop plumbing ----
    def open(self) -> None:
        import asyncio
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._loop.run_forever, daemon=True)
        self._thread.start()
        fut = asyncio.run_coroutine_threadsafe(self._connect(), self._loop)
        try:
            fut.result(timeout=self.timeout)
        except Exception as e:  # noqa: BLE001
            raise TransportError(f"BLE connect to {self.address} failed: {e}") from e

    async def _connect(self) -> None:
        import asyncio
        import time
        from bleak import BleakClient
        self._client = BleakClient(self.address)
        await self._client.connect()
        # Service discovery on the BlueZ backend is async (waits for the
        # ServicesResolved DBus signal); connect() may return before the
        # services are readable. Poll until they are, with a timeout.
        deadline = time.monotonic() + self.timeout
        chars = None
        while time.monotonic() < deadline:
            try:
                chars = self._client.services.characteristics
                break
            except Exception:
                await asyncio.sleep(0.1)
        if chars is None:
            raise TransportError(f"service discovery for {self.address} timed out")
        # bleak >= 3.x exposes characteristics as a dict {handle: char};
        # older versions use a plain list. Normalize to a list either way.
        chars = list(chars.values()) if isinstance(chars, dict) else list(chars)

        # Some JDY-family modules drop/blank the link if we write immediately
        # after service discovery. A short settle beat makes them stable.
        await asyncio.sleep(0.5)

        # pick write + notify characteristics
        def props(c):
            return [p.lower() for p in c.properties]
        write_candidates = [c for c in chars if "write" in props(c) or "write-without-response" in props(c)]
        notify_candidates = [c for c in chars if "notify" in props(c)]

        for pref in self.PREFERRED:
            w = next((c for c in write_candidates if c.uuid == pref), None)
            n = next((c for c in notify_candidates if c.uuid == pref), None)
            if w and n:
                self._write_char = w
                await self._client.start_notify(n.uuid, self._notify)
                return
        if not (write_candidates and notify_candidates):
            raise TransportError("no write/notify characteristics found")
        self._write_char = write_candidates[0]
        await self._client.start_notify(notify_candidates[0].uuid, self._notify)

    def _notify(self, _handle: int, data: bytearray) -> None:
        self.on_rx(bytes(data))

    def write(self, data: bytes) -> None:
        import asyncio
        if self._client is None or self._write_char is None:
            raise TransportError("transport not open")
        # Transparent-bridge modules typically expose only write-without-response;
        # force response=True only when the char needs it. Anything else uses
        # write-without-response (faster, and these modules don't ack anyway).
        props = [p.lower() for p in self._write_char.properties]
        has_write = "write" in props
        has_wowr = "write-without-response" in props
        response = has_write and not has_wowr
        try:
            self._write_chunks(data, response)
        except Exception:
            # JDY-family modules are flaky on a fresh connection: the link can
            # blank its services right after discovery. Reconnect once and retry.
            self._reconnect()
            self._write_chunks(data, response)

    def _write_chunks(self, data: bytes, response: bool) -> None:
        import asyncio
        for i in range(0, len(data), 182):   # stay under default ATT MTU
            chunk = data[i:i + 182]
            fut = asyncio.run_coroutine_threadsafe(
                self._client.write_gatt_char(self._write_char.uuid, chunk, response=response),
                self._loop)
            fut.result(timeout=self.timeout)

    def _reconnect(self) -> None:
        import asyncio
        if self._client is not None:
            try:
                asyncio.run_coroutine_threadsafe(self._client.disconnect(), self._loop).result(timeout=5)
            except Exception:
                pass
        self._client = None
        self._write_char = None
        fut = asyncio.run_coroutine_threadsafe(self._connect(), self._loop)
        fut.result(timeout=self.timeout + 10)

    def close(self) -> None:
        self._closing = True
        if self._loop is not None:
            import asyncio
            async def _dc():
                if self._client is not None:
                    try:
                        await self._client.disconnect()
                    except Exception:
                        pass
            asyncio.run_coroutine_threadsafe(_dc(), self._loop).result(timeout=5)
            self._loop.call_soon_threadsafe(self._loop.stop)
            self._loop = None

    def __enter__(self):
        self.open()
        return self

    def __exit__(self, *exc):
        self.close()


def scan_serial():
    """List candidate serial ports (USB CDC/FTDI/CH340...)."""
    from serial.tools import list_ports
    ports = list_ports.comports()
    return [(p.device, f"{p.description} {p.hwid}".strip()) for p in ports]


def scan_ble(timeout: float = 5.0):
    """Scan BLE adverts. Returns [(address, name)]. Run in its own loop."""
    import asyncio
    from bleak import BleakScanner

    async def _run():
        return await BleakScanner.discover(timeout=timeout)

    return [(d.address, d.name or "?") for d in asyncio.run(_run())]
