#!/usr/bin/env python3
"""
ble_probe.py - standalone BLE diagnostics for STM32F103 + transparent bridge.

Answers three questions without trusting the OTA tool:

  1. What MTU did the OS actually negotiate, and what does bleak report?
  2. What is the bridge's per-packet forwarding limit (the 128 B question)?
  3. Does the device answer a raw PING, and how fast?

Standalone: only needs `pip install bleak`. Copy it anywhere.

Examples
--------
    # find the module (name-less, random static address)
    python ble_probe.py --scan --service 0000ffe0-0000-1000-8000-00805f9b34fb

    # MTU + raw ping
    python ble_probe.py --address AA:BB:CC:DD:EE:FF --mtu --ping

    # sweep packet sizes 32..256, 2 reps each (the 128 B cliff)
    python ble_probe.py --address AA:BB:CC:DD:EE:FF --sweep 32 256 4 --reps 2
"""
from __future__ import annotations

import argparse
import asyncio
import time

SOF0, SOF1 = 0xAA, 0x55
PREFERRED = (
    "0000ffe1-0000-1000-8000-00805f9b34fb",
    "0000fff1-0000-1000-8000-00805f9b34fb",
    "0000ffb1-0000-1000-8000-00805f9b34fb",
)


def crc16_modbus(data: bytes) -> int:
    crc = 0xFFFF
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if (crc & 1) else (crc >> 1)
    return crc & 0xFFFF


def build_frame(cmd: int, payload: bytes = b"") -> bytes:
    crc = crc16_modbus(bytes([cmd, len(payload) >> 8, len(payload) & 0xFF]) + payload)
    return (bytes([SOF0, SOF1, cmd, len(payload) >> 8, len(payload) & 0xFF])
            + payload + bytes([crc >> 8, crc & 0xFF]))


PING = build_frame(0x10)


class Rx:
    """Incremental frame parser that keeps completed frames for the caller."""

    def __init__(self) -> None:
        self.buf = bytearray()
        self.frames: list[tuple[int, bytes]] = []

    def feed(self, data: bytes) -> None:
        self.buf.extend(data)
        while True:
            i = 0
            while i < len(self.buf) - 1 and not (self.buf[i] == SOF0 and self.buf[i + 1] == SOF1):
                i += 1
            if i >= len(self.buf) - 1:
                if len(self.buf) > 1:
                    del self.buf[:-1]
                return
            if i:
                del self.buf[:i]
            if len(self.buf) < 5:
                return
            plen = (self.buf[3] << 8) | self.buf[4]
            if plen > 1024:
                del self.buf[:1]
                continue
            total = 5 + plen + 2
            if len(self.buf) < total:
                return
            body = bytes(self.buf[:total])
            del self.buf[:total]
            if crc16_modbus(body[2:5 + plen]) != ((body[5 + plen] << 8) | body[5 + plen + 1]):
                continue
            self.frames.append((body[2], body[5:5 + plen]))

    def take(self) -> list[tuple[int, bytes]]:
        out, self.frames = self.frames, []
        return out

    def clear(self) -> None:
        self.buf.clear()
        self.frames.clear()


async def connect(address: str):
    from bleak import BleakClient
    client = BleakClient(address)
    await client.connect()

    deadline = time.monotonic() + 10
    chars = None
    while time.monotonic() < deadline:
        try:
            chars = client.services.characteristics
            break
        except Exception:
            await asyncio.sleep(0.1)
    if chars is None:
        raise RuntimeError("service discovery timed out")
    chars = list(chars.values()) if isinstance(chars, dict) else list(chars)

    def props(c):
        return [p.lower() for p in c.properties]

    write_c = [c for c in chars if "write" in props(c) or "write-without-response" in props(c)]
    notify_c = [c for c in chars if "notify" in props(c)]
    if not write_c or not notify_c:
        raise RuntimeError("no write/notify characteristics")

    w = n = None
    for pref in PREFERRED:
        w = next((c for c in write_c if c.uuid == pref), None)
        n = next((c for c in notify_c if c.uuid == pref), None)
        if w and n:
            break
    if not (w and n):
        w, n = write_c[0], notify_c[0]

    rx = Rx()

    def on_notify(_h, data: bytearray):
        rx.feed(bytes(data))

    await client.start_notify(n.uuid, on_notify)
    await asyncio.sleep(0.4)   # let flaky JDY modules settle
    return client, w, n, rx


def use_response(w) -> bool:
    p = [x.lower() for x in w.properties]
    return ("write" in p) and ("write-without-response" not in p)


async def mtu_report(client, w) -> None:
    print("---- MTU ----")
    print(f"  characteristic       : {w.uuid}  {w.properties}")
    try:
        print(f"  client.mtu_size      : {client.mtu_size}")
    except Exception as e:
        print(f"  client.mtu_size      : ERROR {e}")
    try:
        print(f"  max_write_without_rsp: {w.max_write_without_response_size}")
    except Exception as e:
        print(f"  max_write_without_rsp: ERROR {e}")
    backend = getattr(client, "_backend", None)
    acquire = getattr(backend, "_acquire_mtu", None) if backend else None
    if acquire is None:
        print("  _backend._acquire_mtu: not available on this backend (WinRT)")
        return
    try:
        await acquire()
        print(f"  after _acquire_mtu   : client.mtu_size={client.mtu_size}, "
              f"max_write_without_rsp={w.max_write_without_response_size}")
    except Exception as e:
        print(f"  _acquire_mtu failed  : {e}")


async def raw_ping(client, w, rx: Rx, reps: int = 3) -> bool:
    print("---- raw PING ----")
    any_ok = False
    for i in range(reps):
        rx.clear()
        t0 = time.perf_counter()
        try:
            await client.write_gatt_char(w.uuid, PING, response=use_response(w))
        except Exception as e:
            print(f"  try {i + 1}: WRITE FAILED: {e}")
            continue
        got = False
        deadline = time.monotonic() + 1.0
        while time.monotonic() < deadline:
            if any(cmd == 0x90 for cmd, _ in rx.take()):
                print(f"  try {i + 1}: PING ok in {(time.perf_counter() - t0) * 1000:.1f} ms")
                got = any_ok = True
                break
            await asyncio.sleep(0.005)
        if not got:
            print(f"  try {i + 1}: no response")
        await asyncio.sleep(0.1)
    return any_ok


async def sweep(client, w, rx: Rx, lo: int, hi: int, step: int, reps: int) -> None:
    """Last L whose trailing PING still gets an answer = per-packet limit."""
    print("---- packet-size sweep ----")
    print(f"{'len':>5} | result")
    print("-" * 44)
    ok_sizes: list[int] = []
    first_fail = None
    for size in range(lo, hi + 1, step):
        if size < len(PING):
            continue
        results = []
        for _ in range(reps):
            rx.clear()
            packet = b"\x5A" * (size - len(PING)) + PING
            try:
                await client.write_gatt_char(w.uuid, packet, response=use_response(w))
            except Exception as e:
                results.append(f"write-blocked({e.__class__.__name__})")
                break
            got = False
            deadline = time.monotonic() + 0.5
            while time.monotonic() < deadline:
                if any(cmd == 0x90 for cmd, _ in rx.take()):
                    got = True
                    break
                await asyncio.sleep(0.005)
            results.append("ok" if got else "no-reply")
            await asyncio.sleep(0.1)
        label = results[0] if len(set(results)) == 1 else "/".join(results)
        print(f"{size:5d} | {label}")
        if all(r == "ok" for r in results):
            ok_sizes.append(size)
        elif first_fail is None:
            first_fail = size
    print("-" * 44)
    if ok_sizes:
        print(f"last fully delivered packet size = {max(ok_sizes)}")
    if first_fail is not None:
        print(f"first failing packet size        = {first_fail}")
    if ok_sizes and first_fail is not None and max(ok_sizes) > first_fail:
        print("note: non-monotonic (some larger sizes worked); bridge behaviour is unstable")


async def scan(service: str | None, timeout: float) -> None:
    from bleak import BleakScanner
    kwargs = {"service_uuids": [service]} if service else {}
    found = await BleakScanner.discover(timeout, return_adv=True, **kwargs)
    print(f"found {len(found)} device(s)")
    for addr, (dev, adv) in sorted(found.items()):
        name = dev.name or "?"
        print(f"{addr:20s} rssi={adv.rssi:4d}  {name}")
        if adv.service_uuids:
            print(f"{'':20s} services: {', '.join(adv.service_uuids)}")


async def main_async(args) -> int:
    if args.scan:
        await scan(args.service, args.timeout)
        return 0
    if not args.address:
        print("error: --address required (or --scan)")
        return 2

    print(f"connecting to {args.address} ...")
    client, w, n, rx = await connect(args.address)
    print(f"connected. write={w.uuid} notify={n.uuid}")
    try:
        if args.mtu:
            await mtu_report(client, w)
        if args.ping:
            await raw_ping(client, w, rx, reps=args.reps)
        if args.sweep:
            lo, hi, step = args.sweep
            await sweep(client, w, rx, lo, hi, step, args.reps)
    finally:
        try:
            await client.stop_notify(n.uuid)
        except Exception:
            pass
        await client.disconnect()
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="BLE diagnostics for STM32F103 transparent bridges")
    ap.add_argument("--scan", action="store_true", help="scan instead of connecting")
    ap.add_argument("--service", help="filter scan by service UUID")
    ap.add_argument("--timeout", type=float, default=8.0, help="scan timeout (s)")
    ap.add_argument("--address", help="device address / UUID")
    ap.add_argument("--mtu", action="store_true", help="print MTU and max write size")
    ap.add_argument("--ping", action="store_true", help="send a raw PING frame")
    ap.add_argument("--sweep", nargs=3, type=int, metavar=("LO", "HI", "STEP"),
                    help="sweep packet sizes to find the bridge limit")
    ap.add_argument("--reps", type=int, default=2, help="repetitions per size (default 2)")
    args = ap.parse_args()
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    raise SystemExit(main())
