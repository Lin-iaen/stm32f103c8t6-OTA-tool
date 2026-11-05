"""
transport.py - byte-pipe transports (serial / BLE) behind one interface.

A transport is just: open(), close(), write(bytes), and a callback that
receives inbound bytes. The Device layer owns framing; transports stay dumb
so serial and BLE are fully interchangeable (same protocol over any pipe).
"""
from __future__ import annotations

import threading
from typing import Callable

# A transparent BLE bridge is not a plain byte pipe: it forwards at most one
# GATT write's worth of bytes per UART burst. Many JDY-family modules have a
# 128-byte internal buffer and silently drop the tail of anything larger, so
# stay below that. 120 is even (BL_DATA wants even chunks) and leaves headroom.
BRIDGE_MAX_PACKET = 120
# Smallest ATT payload every BLE 4.0 stack must accept (MTU 23 - 3).
ATT_MIN_PAYLOAD = 20
# bleak returns 23 for `mtu_size` when BlueZ has not acquired the real value.
# A real max_write of 23 bytes is possible but rare; treating it as "unknown"
# and falling back on the first length error is cheaper than being stuck at
# 20 B/packet for the whole OTA.
BLEAK_MTU_UNKNOWN = 23


def plan_chunk_size(max_write: int | None) -> int:
    """Pick a GATT payload size safe for both the OS and the bridge.

    `max_write` is the characteristic's `max_write_without_response_size`:
      - WinRT: negotiated MTU - 3
      - BlueZ >= 5.62: characteristic MTU - 3
      - BlueZ < 5.62: 20 (means "unknown", not a real 23-byte MTU)

    Values <= BLEAK_MTU_UNKNOWN are treated as unknown: try the bridge limit
    and let the length-error fallback in _write_chunks() drop to 20 if the real
    MTU turns out to be minimal.
    """
    if max_write is None or max_write <= BLEAK_MTU_UNKNOWN:
        return BRIDGE_MAX_PACKET
    return max(ATT_MIN_PAYLOAD, min(max_write, BRIDGE_MAX_PACKET))


def _is_length_error(exc: BaseException) -> bool:
    """True when a write failed because the payload exceeded the MTU/bridge."""
    text = str(exc).lower()
    return any(marker in text for marker in (
        "-2147024809",          # WinRT E_INVALIDARG
        "invalidargs",          # BlueZ D-Bus InvalidArgs
        "invalid value",
        "invalidvaluelength",
        "failed to initiate write",  # BlueZ when len(data) > MTU-3
        "mtu",
        "length",
    ))


class TransportError(RuntimeError):
    pass


def _connect_error_message(address: str, exc: BaseException) -> str:
    """Human-readable connect failure.

    bleak/WinRT raises HRESULT-backed exceptions whose str() is sometimes
    empty, which used to leave the user with a bare "failed: ". Always keep
    the exception type, and fall back to repr() when the message is blank.
    """
    detail = str(exc).strip() or repr(exc)
    return f"BLE connect to {address} failed: {type(exc).__name__}: {detail}"


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


# ---------------------------------------------------------------------------
# Transparent-bridge GATT pairing
# ---------------------------------------------------------------------------
#
# A "transparent bridge" exposes one serial pipe over BLE, but the vendors do
# not agree on how to model it in GATT. Two layouts are in the wild:
#
#   combined  one characteristic carries both directions
#             (JDY-69: FFE1 AND FFE2 each support write+notify)
#             -> write and notify must be THE SAME characteristic
#
#   split     one characteristic for downlink, another for uplink
#             (VG6328A/I6328A: FFE1 = Write Without Response, FFE2 = Notify)
#             -> write and notify MUST be DIFFERENT characteristics
#
# Picking "the first characteristic that has write and notify" silently fails
# on the split layout (no candidate matches), and naively taking the first of
# each list can cross-pair the wrong pair on a module that exposes several
# services (the JDY-69 has ffe0/ffe1/ffe2 and ff10/ff11/ff12). So the rule is
# explicit and ordered:
#
#   1. same characteristic, both directions  -> combined layout
#   2. write + notify in the SAME service    -> split layout
#   3. write + notify from different services -> last resort
#
# Priority inside each candidate set goes by the well-known suffix list below,
# so a module that also exposes configuration channels still resolves to the
# data channel.
BRIDGE_WRITE_UUIDS = (
    "0000ffe1-0000-1000-8000-00805f9b34fb",
    "0000fff1-0000-1000-8000-00805f9b34fb",
    "0000ffb1-0000-1000-8000-00805f9b34fb",
    "00002af1-0000-1000-8000-00805f9b34fb",
)
BRIDGE_NOTIFY_UUIDS = (
    "0000ffe1-0000-1000-8000-00805f9b34fb",
    "0000ffe2-0000-1000-8000-00805f9b34fb",
    "0000fff1-0000-1000-8000-00805f9b34fb",
    "0000fff2-0000-1000-8000-00805f9b34fb",
    "0000ffb1-0000-1000-8000-00805f9b34fb",
    "0000ffb2-0000-1000-8000-00805f9b34fb",
    "00002af1-0000-1000-8000-00805f9b34fb",
)


def _ch_props(ch) -> list[str]:
    return [str(p).lower() for p in (ch.properties or [])]


def _can_write(ch) -> bool:
    p = _ch_props(ch)
    return "write" in p or "write-without-response" in p


def _can_notify(ch) -> bool:
    p = _ch_props(ch)
    return "notify" in p or "indicate" in p


def _rank(ch, preferred: tuple[str, ...]) -> int:
    """Index in the preferred list, or len(preferred) for anything else."""
    uuid = str(ch.uuid).lower()
    for i, want in enumerate(preferred):
        if uuid == want:
            return i
    return len(preferred)


def _service_of(ch) -> str | None:
    """Owning service UUID, or None when the backend does not expose it."""
    for attr in ("service_uuid",):
        value = getattr(ch, attr, None)
        if value:
            return str(value).lower()
    svc = getattr(ch, "service", None)
    uuid = getattr(svc, "uuid", None)
    return str(uuid).lower() if uuid else None


def pick_bridge_pair(characteristics):
    """Choose (write_char, notify_char) for a transparent BLE bridge.

    `characteristics` is a flat iterable of BleakGATTCharacteristic (bleak
    >= 0.21 exposes services.characteristics as a dict {handle: char}; pass
    `.values()`). Returns (None, None) when the pipe cannot be formed.

    The returned pair may be the same object (combined layout) - callers
    should not assume two distinct characteristics.
    """
    chars = list(characteristics)
    writable = [c for c in chars if _can_write(c)]
    notifiable = [c for c in chars if _can_notify(c)]

    if not writable or not notifiable:
        return None, None

    writable.sort(key=lambda c: _rank(c, BRIDGE_WRITE_UUIDS))
    notifiable.sort(key=lambda c: _rank(c, BRIDGE_NOTIFY_UUIDS))

    # 1) combined layout: one characteristic for both directions. Prefer an
    #    exact UUID mentioned in BOTH lists (FFE1 is such a case), because that
    #    is what every JDY/HC-08 style module exposes.
    both = [c for c in chars if _can_write(c) and _can_notify(c)]
    if both:
        def both_rank(c):
            return min(_rank(c, BRIDGE_WRITE_UUIDS), _rank(c, BRIDGE_NOTIFY_UUIDS))
        both.sort(key=both_rank)
        best = both[0]
        return best, best

    # 2) split layout inside one service: take the best-ranked writer and the
    #    best-ranked notifier that live in the same service.
    for w in writable:
        w_svc = _service_of(w)
        if w_svc is None:
            continue
        for n in notifiable:
            if str(n.uuid).lower() == str(w.uuid).lower():
                continue
            if _service_of(n) == w_svc:
                return w, n

    # 3) last resort: best writer + best notifier anywhere.
    n = notifiable[0]
    if str(n.uuid).lower() == str(writable[0].uuid).lower():
        n = next((c for c in notifiable
                  if str(c.uuid).lower() != str(writable[0].uuid).lower()), n)
    return writable[0], n


class BleTransport:
    """BLE GATT pipe for transparent-bridge modules (ECB02H / JDY / HC-08...).

    Connects via BlueZ (Linux) or WinRT (Windows) using bleak. Discovered
    characteristics are paired by pick_bridge_pair(), which handles both the
    combined layout (one characteristic for both directions, JDY/HC-08) and
    the split layout (separate write and notify characteristics, VG6328A).
    Writes are chunked adaptively: the characteristic's
    max_write_without_response_size, capped at 120 bytes (transparent bridges
    often drop anything over 128 B), with a 20-byte fallback if the OS still
    rejects the payload.
    """

    def __init__(self, address: str, on_rx: Callable[[bytes], None] = lambda d: None,
                 timeout: float = 10.0):
        self.address = address
        self.on_rx = on_rx
        self.timeout = timeout
        self._loop = None
        self._thread: threading.Thread | None = None
        self._client = None
        self._write_char = None
        self._notify_char = None
        self._chunk_size = BRIDGE_MAX_PACKET
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
            # Do not leak the background loop/thread when connect fails.
            fut.cancel()
            try:
                self._loop.call_soon_threadsafe(self._loop.stop)
                self._thread.join(timeout=2)
            finally:
                self._loop = None
                self._thread = None
            raise TransportError(_connect_error_message(self.address, e)) from e

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

        # Pick the serial pipe. The layout differs per vendor (combined vs
        # split write/notify), so the selection lives in pick_bridge_pair()
        # and is shared with the tools - three copies of this logic is how a
        # split-layout module ended up looking "incompatible".
        w, n = pick_bridge_pair(chars)
        if w is None or n is None:
            raise TransportError("no write/notify characteristics found")
        self._write_char = w
        self._notify_char = n
        try:
            max_write = int(w.max_write_without_response_size)
        except Exception:
            max_write = None
        self._chunk_size = plan_chunk_size(max_write)
        await self._client.start_notify(n.uuid, self._notify)

    def describe(self) -> str:
        """One line naming the paired characteristics, for bug reports.

        Which characteristic was chosen is the first thing to check when a new
        bridge "connects but transfers nothing", and neither value is visible
        from the outside otherwise.
        """
        if self._write_char is None or self._notify_char is None:
            return "bridge: not connected"
        layout = "combined" if self._write_char is self._notify_char else "split"
        return (f"bridge: {layout} layout, "
                f"write={self._write_char.uuid}, notify={self._notify_char.uuid}, "
                f"chunk={self._chunk_size}B")

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
        except Exception as e:
            # A length error means the payload is too big for the MTU/bridge;
            # reconnecting cannot fix that, and _write_chunks already tried the
            # 20-byte fallback. Surface it instead of retrying.
            if _is_length_error(e):
                raise TransportError(f"BLE write failed (payload too large?): {e}") from e
            # Otherwise assume the JDY link blanked: reconnect once and retry.
            try:
                self._reconnect()
                self._write_chunks(data, response)
            except Exception as e2:
                raise TransportError(f"BLE write failed after reconnect: {e2}") from e2

    def _write_chunks(self, data: bytes, response: bool) -> None:
        import asyncio
        off = 0
        while off < len(data):
            chunk = data[off:off + self._chunk_size]
            try:
                fut = asyncio.run_coroutine_threadsafe(
                    self._client.write_gatt_char(self._write_char.uuid, chunk, response=response),
                    self._loop)
                fut.result(timeout=self.timeout)
            except Exception as e:
                if self._chunk_size > ATT_MIN_PAYLOAD and _is_length_error(e):
                    # MTU turned out smaller than reported (or the bridge is
                    # stricter): drop to the guaranteed-safe ATT payload and
                    # retry this same offset.
                    self._chunk_size = ATT_MIN_PAYLOAD
                    continue
                raise
            off += len(chunk)

    def _reconnect(self) -> None:
        import asyncio
        if self._client is not None:
            try:
                asyncio.run_coroutine_threadsafe(self._client.disconnect(), self._loop).result(timeout=5)
            except Exception:
                pass
        self._client = None
        self._write_char = None
        self._notify_char = None
        fut = asyncio.run_coroutine_threadsafe(self._connect(), self._loop)
        fut.result(timeout=self.timeout + 10)

    def close(self) -> None:
        self._closing = True
        loop = self._loop
        if loop is None:
            return
        import asyncio

        async def _dc():
            if self._client is not None:
                try:
                    await self._client.disconnect()
                except Exception:
                    pass

        try:
            asyncio.run_coroutine_threadsafe(_dc(), loop).result(timeout=5)
        except Exception:
            pass
        try:
            loop.call_soon_threadsafe(loop.stop)
        except Exception:
            pass
        if self._thread is not None:
            self._thread.join(timeout=2)
        self._loop = None
        self._thread = None

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


def _advertised_services(device) -> list[str]:
    """Advertised service UUIDs from a bleak BLEDevice, across backends.

    BlueZ exposes them as details["props"]["UUIDs"]; newer bleak also fills a
    `metadata` dict on some backends. Returns [] when neither is available.
    """
    details = getattr(device, "details", None)
    if isinstance(details, dict):
        props = details.get("props") or {}
        uuids = list(props.get("UUIDs") or [])
        if uuids:
            return [str(u) for u in uuids]
    meta = getattr(device, "metadata", None)
    if isinstance(meta, dict):
        return [str(u) for u in (meta.get("uuids") or [])]
    return []


def scan_label(name: str | None, services: list[str]) -> str:
    """One column for `fwb scan-ble`: name, else the advertised service UUIDs.

    Transparent bridges usually advertise no name (random static address), so
    printing "?" made the scan list useless. Showing the first service UUIDs
    is enough to recognise the module and to know what to pass to --service.
    """
    if name:
        return name
    if services:
        return "{" + ",".join(_short_uuid(u) for u in services[:3]) + "}"
    return "?"


def _short_uuid(uuid: str) -> str:
    """'0000ffe0-0000-1000-8000-00805f9b34fb' -> 'ffe0'."""
    head = uuid.split("-")[0].lower()
    return head[-4:] if len(head) == 8 and head.startswith("0000") else head


def scan_ble(timeout: float = 5.0, service: str | None = None):
    """Scan BLE adverts. Returns [(address, name, service_uuids)].

    `service` filters on an advertised service UUID. Needed for modules that
    do not advertise a name and use a random static address.
    """
    import asyncio
    from bleak import BleakScanner

    async def _run():
        kwargs = {"service_uuids": [service]} if service else {}
        return await BleakScanner.discover(timeout=timeout, **kwargs)

    return [(d.address, d.name, _advertised_services(d)) for d in asyncio.run(_run())]
