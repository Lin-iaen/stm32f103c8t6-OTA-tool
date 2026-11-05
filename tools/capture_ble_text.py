#!/usr/bin/env python3
"""Grab plain-text output the firmware prints on USART1, over BLE.

The self-test report goes out on USART1 -> JDY-69A -> BLE, as plain ASCII, and
it is printed exactly once after reset. So the BLE link has to be *already
connected* when the board restarts, otherwise the text is transmitted into the
void. This script does that ordering: connect, start the reset, keep listening.

  python3 tools/capture_boot.py --ble 13:22:88:32:25:F7 --reset-ble

With --reset-ble it asks the running app to reboot (APP_REBOOT), which is
enough here because the reset happens inside the app. If the board is stuck in
the bootloader, reset it by hand (or with --reset-swd) and rerun.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
import threading
import time
from pathlib import Path

# Resolve the package root from this file, not from the cwd and not by
# string-splitting a path: `cd tools && python live_plot.py` must work
# as well as `python host/tools/live_plot.py`.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fwb_tool.transport import pick_bridge_pair, scan_ble  # noqa: E402


def pick_pair(services):
    """Return (write_char, notify_char) for the transparent-UART service.

    Thin wrapper kept for callers/tests that pass a services object; the real
    logic lives in fwb_tool.transport.pick_bridge_pair() so this tool, live_plot
    and the OTA transport cannot disagree about which characteristic is the
    serial pipe. A module with several services (this bench link exposes
    ffe0/ffe1/ffe2 and ff10/ff11/ff12) needs the same answer in all three.
    """
    chars = []
    for svc in services:
        chars.extend(svc.characteristics)
    return pick_bridge_pair(chars)


async def run(args) -> int:
    from bleak import BleakClient

    # The BLE bridge on this bench link drops connections often enough that a
    # single attempt wastes the whole window (and the measurement cannot be
    # repeated retroactively if it was a physical event like "pinch the probe").
    # Retry the connect a few times before giving up.
    last_err = None
    for attempt in range(1, 4):
        try:
            return await _run_once(args)
        except Exception as exc:            # noqa: BLE001 - report and retry
            last_err = exc
            print(f"[!] attempt {attempt} failed: {type(exc).__name__}: {exc}",
                  flush=True)
            if attempt < 3:
                await asyncio.sleep(2.0)
    print(f"[!] giving up: {last_err}", flush=True)
    return 2


async def _run_once(args) -> int:
    from bleak import BleakClient

    buf = bytearray()
    done = threading.Event()

    def on_notify(_char, data: bytearray):
        buf.extend(data)
        sys.stdout.write(data.decode("utf-8", "replace"))
        sys.stdout.flush()
        if args.stop_on and args.stop_on.encode() in buf:
            done.set()

    print(f"[*] connecting to {args.ble} ...", flush=True)
    async with BleakClient(args.ble, timeout=20.0) as client:
        services = client.services
        wch, nch = pick_pair(services)
        if wch is None or nch is None:
            print("[!] no write/notify pair found on this device", flush=True)
            return 2
        print(f"[*] write={wch.uuid} notify={nch.uuid}", flush=True)
        await client.start_notify(nch, on_notify)

        if args.reset_ble:
            # Reuse the CLI's own frame builder so the CRC cannot drift.
            from fwb_tool.protocol import APP_REBOOT, build_frame
            frame = build_frame(APP_REBOOT)
            print("[*] sending APP_REBOOT", flush=True)
            await client.write_gatt_char(wch, frame, response=False)

        deadline = time.time() + args.timeout
        while time.time() < deadline and not done.is_set():
            await asyncio.sleep(0.1)

    print(flush=True)
    return 0


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--ble", required=True, help="BLE address (see fwb scan-ble)")
    p.add_argument("--timeout", type=float, default=15.0,
                   help="listen this long at most (restarts on a connect retry)")
    p.add_argument("--stop-on", default="",
                   help="stop early once this text has been received "
                        "(default: wait the whole --timeout)")
    p.add_argument("--reset-ble", action="store_true",
                   help="send APP_REBOOT over the same link right after connecting")
    return asyncio.run(run(p.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
