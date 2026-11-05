#!/usr/bin/env python3
"""
bridge_selftest.py - prove a transparent BLE bridge before blaming the firmware.

Bring-up of a new BLE-UART module fails in the same handful of ways every
time, and they all look identical from `fwb info`: "timeout waiting for
response". This tool separates the layers instead of guessing, because the
fix is completely different for each:

    layer            what is checked                  typical symptom
    -----            ----------------                  ---------------
    GATT pairing     write/notify characteristic       "no write/notify pair"
    downlink         BLE -> UART, byte exact           firmware never receives
    uplink           UART -> BLE, byte exact           firmware answers, host blind
    AT mode          module still in command mode      AT+ENAT was never exited
    firmware         MCU answers a protocol ping       wiring/baud/power

The downlink and uplink tests loop a local pattern through the module, so they
need NOTHING on the far side of the UART. That is the point: a module that
cannot carry `DE AD BE EF` intact will never carry a 36 KB OTA image, and no
amount of host-side retry tuning will change that.

Usage:
    bridge_selftest.py --ble 33:0B:01:2D:57:59
    bridge_selftest.py --ble ... --serial /dev/ttyACM0   # loopback pair
    bridge_selftest.py --serial /dev/ttyACM0             # AT mode only
"""
from __future__ import annotations

import argparse
import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fwb_tool.transport import pick_bridge_pair  # noqa: E402

MARKER = b"\xde\xad\xbe\xef"
SIZES = (1, 4, 8, 20, 60, 120, 200)


def ok(msg):
    print(f"  [ ok ] {msg}")


def bad(msg):
    print(f"  [FAIL] {msg}")


def info(msg):
    print(f"  [info] {msg}")


async def wait_services(client, timeout=15.0):
    """Wait until BlueZ has finished GATT discovery.

    bleak's ``client.services`` raises ``BleakError("Service Discovery has not
    been performed yet")`` until the async discovery completes; on BlueZ that
    is a short but real window after ``connect()`` returns. Touching the
    property too early used to abort the whole self-test with a traceback.
    """
    from bleak.exc import BleakError

    deadline = asyncio.get_event_loop().time() + timeout
    last = None
    while True:
        try:
            return list(client.services)
        except BleakError as e:          # discovery still in flight
            last = e
        if asyncio.get_event_loop().time() >= deadline:
            raise RuntimeError(f"GATT discovery did not finish in {timeout:.0f}s: {last}")
        await asyncio.sleep(0.2)


async def check_gatt(client):
    """Report the paired characteristics; this alone diagnoses split layout."""
    chars = []
    for svc in await wait_services(client):
        for ch in svc.characteristics:
            try:
                ch.service_uuid = svc.uuid
            except Exception:
                pass
            chars.append(ch)
    write, notify = pick_bridge_pair(chars)
    if write is None:
        bad("no usable write/notify pair on this device")
        for svc in await wait_services(client):
            for ch in svc.characteristics:
                info(f"{ch.uuid} {ch.properties}")
        return None, None
    layout = "combined" if write is notify else "split"
    ok(f"{layout} layout: write={write.uuid} notify={notify.uuid}")
    return write, notify


async def check_roundtrip(client, write_uuid, notify_uuid, serial_port):
    """Push patterns through the module; needs a peer on the UART to echo.

    Without a peer the uplink section is skipped, which is itself useful: an
    uplink that stays silent while a peer is wired is the wiring fault.
    """
    rx = []

    def on_notify(_h, data):
        rx.append(bytes(data))

    await client.start_notify(notify_uuid, on_notify)
    await asyncio.sleep(0.5)

    peer = None
    if serial_port:
        import serial
        peer = serial.Serial(serial_port, 115200, timeout=0.3)
        info(f"using {serial_port} as the far-side peer")

    print("\n-- downlink (BLE -> UART) --")
    down_ok = True
    for n in SIZES:
        payload = bytes((i * 7 + 3) & 0xFF for i in range(n))
        rx.clear()
        await client.write_gatt_char(write_uuid, payload, response=False)
        await asyncio.sleep(0.3)
        if peer is not None:
            got = peer.read(n + 8)
            if got == payload:
                ok(f"{n:3d} B exact")
            else:
                down_ok = False
                bad(f"{n:3d} B -> got {len(got)} B: {got[:16].hex()}")
        else:
            ok(f"{n:3d} B written (no peer to verify)")
    if peer is None:
        print("\n-- uplink (UART -> BLE) --")
        info("skipped: pass --serial to wire a peer and verify this direction")
        return down_ok, None

    print("\n-- uplink (UART -> BLE) --")
    up_ok = True
    for n in SIZES:
        payload = bytes((i * 7 + 3) & 0xFF for i in range(n))
        rx.clear()
        peer.reset_input_buffer()
        peer.write(payload)
        peer.flush()
        await asyncio.sleep(0.4)
        got = b"".join(rx)
        if got == payload:
            ok(f"{n:3d} B exact")
        else:
            up_ok = False
            bad(f"{n:3d} B -> got {len(got)} B: {got[:16].hex()}")
    peer.close()
    return down_ok, up_ok


def check_at_mode(serial_port):
    """Is the module still in command mode? Then it forwards no data at all."""
    import serial
    print("\n-- AT command mode --")
    s = serial.Serial(serial_port, 115200, timeout=0.4)
    try:
        # Drain first: the loopback test just pushed data through, and leftover
        # bytes in the OS buffer are not an AT reply. Only an actual "OK"/"ERR"
        # line means command mode.
        s.reset_input_buffer()
        time.sleep(0.2)
        s.reset_input_buffer()
        s.write(b"AT\r\n")
        s.flush()
        time.sleep(0.8)
        reply = s.read(64)
        text = reply.decode("ascii", "replace").strip()
        if text in ("OK", "ERR") or text.startswith(("OK", "ERR")):
            bad(f"module answers AT ({text!r}) -> still in command mode; "
                f"send AT+EXAT and retest")
            return False
        ok("transparent mode (no AT reply)")
        return True
    finally:
        s.close()


async def main(args):
    from bleak import BleakClient

    results = {}
    async with BleakClient(args.ble, timeout=25.0) as client:
        print(f"connected to {args.ble}")
        write, notify = await check_gatt(client)
        if write is None:
            return 2
        down, up = await check_roundtrip(client, write.uuid, notify.uuid, args.serial)
        results["downlink"] = down
        results["uplink"] = up

    if args.serial:
        results["at_mode"] = check_at_mode(args.serial)

    print("\n== summary ==")
    for k, v in results.items():
        if v is None:
            print(f"  {k:10s} not tested")
        else:
            print(f"  {k:10s} {'PASS' if v else 'FAIL'}")
    return 0 if all(v for v in results.values() if v is not None) else 1


def cli():
    p = argparse.ArgumentParser(description=__doc__,
                               formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--ble", help="BLE address of the bridge (see fwb scan-ble)")
    p.add_argument("--serial", help="serial port wired to the same module, "
                                    "for loopback / AT-mode checks")
    args = p.parse_args()
    if not args.ble:
        p.error("--ble is required")
    raise SystemExit(asyncio.run(main(args)))


if __name__ == "__main__":
    cli()
