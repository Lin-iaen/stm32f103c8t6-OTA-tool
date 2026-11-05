#!/usr/bin/env python3
"""burst_probe.py - characterise the leading bytes of every BLE uplink burst.

Motivation: on the VG6328A the uplink arrives as

    ff ff ff ff ff ff | a9 ab 15 00 10 <payload> <CRC>
    ^^^^^^^^^^^^^^^^^   ^^^^^^^^^
    junk prefix         the real frame's first 3 bytes mangled

while the same frame through a JDY-69 has no prefix and no damage. To find out
WHY, we need to know whether the damage belongs to the *burst* or to the fact
that the module has just forwarded a downlink write.

So this tool measures two populations separately:

  * unsolicited - the App emits 1 Hz telemetry on its own, so the module has
    not just transmitted anything. A clean header here means the damage needs
    a preceding downlink (turnaround), rather than merely an idle->active edge.
  * solicited   - a downlink write immediately precedes each burst.

Per burst it reports: total length, leading 0xFF run, whether the frame header
(AA 55) starts exactly where the junk ends, and whether the CRC validates.

Usage:
    .venv/bin/python tools/burst_probe.py --ble AA:BB:CC:DD:EE:FF
    .venv/bin/python tools/burst_probe.py --ble ... --passive 12 --requests 20
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import fwb_tool.protocol as proto
from fwb_tool.protocol import PROTO_SOF0, PROTO_SOF1, build_frame, crc16_modbus
from fwb_tool.transport import pick_bridge_pair


# ---------------------------------------------------------------- analysis
def leading_ff(blob: bytes) -> int:
    n = 0
    while n < len(blob) and blob[n] == 0xFF:
        n += 1
    return n


def locate_frame(blob: bytes, skip: int):
    """Look for a frame starting at or after `skip`.

    Returns (header_ok, crc_ok, cmd, plen).
    header_ok is True only when the frame starts exactly at `skip`, i.e. there
    is no additional junk between the 0xFF run and the frame.
    """
    i = skip
    while i + 7 <= len(blob):
        if blob[i] == PROTO_SOF0 and blob[i + 1] == PROTO_SOF1:
            plen = (blob[i + 3] << 8) | blob[i + 4]
            end = i + 5 + plen + 2
            if end > len(blob):
                return (i == skip, None, blob[i + 2], plen)
            ok = crc16_modbus(blob[i + 2:i + 5 + plen]) == ((blob[end - 2] << 8) | blob[end - 1])
            return (i == skip, ok, blob[i + 2], plen)
        i += 1
    return (False, False, None, None)


def classify(blob: bytes) -> dict:
    nff = leading_ff(blob)
    header_ok, crc_ok, cmd, plen = locate_frame(blob, nff)
    return {"len": len(blob), "ff": nff, "header_ok": header_ok,
            "crc_ok": crc_ok, "cmd": cmd, "plen": plen, "raw": blob}


def report(title: str, samples):
    print(f"\n-- {title} --")
    if not samples:
        print("  (no bursts captured)")
        return
    n = len(samples)
    ff = [s["ff"] for s in samples]
    hdr = sum(1 for s in samples if s["header_ok"])
    crc = sum(1 for s in samples if s["crc_ok"])
    print(f"  bursts={n}  header_ok={hdr}/{n}  crc_ok={crc}/{n}")
    print(f"  leading 0xFF: min={min(ff)} max={max(ff)} avg={sum(ff)/n:.1f}"
          f"   (0 = no junk prefix)")
    damaged = [s for s in samples if not s["header_ok"]]
    for s in damaged[:3]:
        print(f"    damaged: len={s['len']:3d} ff={s['ff']:2d} "
              f"{s['raw'][:14].hex()}")


# ---------------------------------------------------------------- transport
class Link:
    """BLE link that survives the BlueZ discovery window and reconnects."""

    def __init__(self, address, on_notify):
        self.address = address
        self.on_notify = on_notify
        self.client = None
        self.write = None
        self.notify = None

    async def connect(self):
        from bleak import BleakClient
        from bleak.exc import BleakError

        if self.client is not None:
            try:
                await self.client.disconnect()
            except Exception:
                pass

        self.client = BleakClient(self.address, timeout=25.0)
        await self.client.connect()

        # BlueZ finishes GATT discovery *after* connect() returns.
        for _ in range(80):
            try:
                chars = [ch for s in self.client.services for ch in s.characteristics]
                break
            except BleakError:
                await asyncio.sleep(0.2)
        else:
            raise RuntimeError("GATT discovery never completed")

        self.write, self.notify = pick_bridge_pair(chars)
        if self.write is None:
            raise RuntimeError("no usable write/notify pair")
        await self.client.start_notify(self.notify, lambda _h, d: self.on_notify(bytes(d)))
        await asyncio.sleep(0.5)

    async def write_frame(self, data: bytes):
        from bleak.exc import BleakError

        for attempt in range(6):
            if not self.client.is_connected:
                await self.connect()
            try:
                await self.client.write_gatt_char(self.write, data, response=False)
                return
            except BleakError:
                if attempt == 5:
                    raise
                await asyncio.sleep(0.3)
                if not self.client.is_connected:
                    await self.connect()

    async def close(self):
        if self.client is not None:
            try:
                await self.client.disconnect()
            except Exception:
                pass


async def async_main(args) -> int:
    rx = []
    link = Link(args.ble, rx.append)
    await link.connect()
    print(f"bridge: write={link.write.uuid} notify={link.notify.uuid}")

    # Phase A: never write. Only the App's own telemetry arrives.
    rx.clear()
    await asyncio.sleep(args.passive)
    report(f"unsolicited (telemetry only, no downlink for {args.passive:.0f}s)",
           [classify(b) for b in list(rx)])

    # Phase B: immediately preceded by a downlink write.
    frame = build_frame(getattr(proto, args.cmd.upper()))
    solicited = []
    for _ in range(args.requests):
        await asyncio.sleep(args.gap)
        before = len(rx)
        await link.write_frame(frame)
        await asyncio.sleep(0.45)
        solicited.extend(classify(b) for b in rx[before:])
    report("solicited (downlink write right before each burst)", solicited)

    await link.close()
    return 0


def cli():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--ble", required=True)
    p.add_argument("--passive", type=float, default=8.0)
    p.add_argument("--requests", type=int, default=12)
    p.add_argument("--gap", type=float, default=0.5)
    p.add_argument("--cmd", default="APP_PING")
    raise SystemExit(asyncio.run(async_main(p.parse_args())))


if __name__ == "__main__":
    cli()
