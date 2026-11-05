#!/usr/bin/env python3
"""Live curve for the TC-001 MAX6675 reader.

Two jobs, one window:
  1. show the temperature as it arrives, so the direction of a physical event
     (grip, warm water, ice) is visible immediately instead of being inferred
     from a log after the fact;
  2. keep a CSV log next to it, because the curve is evidence only if the raw
     numbers survive the session.

Reading the flags is the whole point of the reader, so invalid samples are
plotted as gaps, never as 0 degC: the task card's lesson was that swallowing an
error code makes "cannot read" look like "0 degC", and a plotting tool can
repeat that mistake just as easily as firmware.

Usage (bleak and matplotlib do not live in the same interpreter on this box):
    PYTHONPATH=host/.venv/lib/python3.12/site-packages \
        /usr/bin/python3 host/tools/live_plot.py --ble 13:22:88:32:25:F7

    # or from a serial port
    host/tools/live_plot.py --port /dev/ttyUSB0

    # no GUI available
    host/tools/live_plot.py --ble ... --terminal
"""
from __future__ import annotations

import argparse
import asyncio
import collections
import csv
import sys
import threading
import time
from pathlib import Path

# Resolve the package root from this file, not from the cwd and not by
# string-splitting a path: `cd tools && python live_plot.py` must work
# as well as `python host/tools/live_plot.py`.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fwb_tool.transport import pick_bridge_pair  # noqa: E402

FLAG_OPEN_TC = 1 << 0
FLAG_NO_MODULE = 1 << 1
FLAG_BAD_ID = 1 << 2

TEMP_INVALID = 0xFFFF


def decode(temp_x4: int, flags: int):
    """Return (celsius or None, reason). None means "do not plot this"."""
    if flags & FLAG_NO_MODULE:
        return None, "no module"
    if flags & FLAG_BAD_ID:
        return None, "bad id"
    if temp_x4 == TEMP_INVALID:
        return None, "invalid"
    return temp_x4 / 4.0, ("open thermocouple" if flags & FLAG_OPEN_TC else "")


# ---------------------------------------------------------------- sources
class BleSource(threading.Thread):
    """Reads plain text lines from the transparent-BLE bridge."""

    daemon = True

    def __init__(self, address: str, on_line):
        super().__init__()
        self.address = address
        self.on_line = on_line
        self.error: Exception | None = None
        self._stop = False

    def stop(self):
        self._stop = True

    def run(self):
        asyncio.run(self._main())

    async def _main(self):
        from bleak import BleakClient

        buf = bytearray()
        while not self._stop:
            try:
                async with BleakClient(self.address, timeout=20.0) as client:
                    ch = self._pick(client.services)
                    if ch is None:
                        raise RuntimeError("no transparent write+notify characteristic")

                    def on_notify(_c, data: bytearray):
                        buf.extend(data)
                        while b"\n" in buf:
                            raw, _, rest = buf.partition(b"\n")
                            buf[:] = rest
                            self.on_line(raw.decode("utf-8", "replace").strip())

                    await client.start_notify(ch, on_notify)
                    print(f"[live] connected, notify={ch.uuid}", file=sys.stderr)
                    while not self._stop and client.is_connected:
                        await asyncio.sleep(0.2)
            except Exception as exc:                       # noqa: BLE001
                self.error = exc
                if self._stop:
                    return
                print(f"[live] link lost ({type(exc).__name__}), reconnecting",
                      file=sys.stderr)
                await asyncio.sleep(2.0)

    @staticmethod
    def _pick(services):
        """The notify characteristic of the transparent serial pipe.

        Delegated to fwb_tool.transport so this tool agrees with `fwb ota` and
        capture_ble_text.py. Returns only the NOTIFY side: a split-layout
        module (VG6328A: FFE1 writes, FFE2 notifies) has no single
        characteristic doing both, which used to make this return None.
        """
        chars = [ch for svc in services for ch in svc.characteristics]
        _write, notify = pick_bridge_pair(chars)
        return notify


def serial_lines(port: str, baud: int, on_line):
    import serial

    ser = serial.Serial(port, baud, timeout=1.0)
    buf = bytearray()
    while True:
        data = ser.read(256)
        if not data:
            continue
        buf.extend(data)
        while b"\n" in buf:
            raw, _, rest = buf.partition(b"\n")
            buf[:] = rest
            on_line(raw.decode("utf-8", "replace").strip())


# ---------------------------------------------------------------- recording
class Recorder:
    """Parses lines, keeps a rolling window, writes CSV."""

    def __init__(self, csv_path: str | None, window_s: float):
        self.window_s = window_s
        self.t: collections.deque[float] = collections.deque()
        self.c: collections.deque[float | None] = collections.deque()
        self.last_raw = ""
        self.last_reason = ""
        self.n_ok = 0
        self.n_bad = 0
        self.t0: float | None = None
        self.csv = None
        if csv_path:
            self.csv = open(csv_path, "w", newline="")
            self.w = csv.writer(self.csv)
            self.w.writerow(["host_epoch_s", "device_ms", "temp_x4", "flags",
                             "celsius", "note"])

    def feed(self, line: str):
        if not line or line.startswith("#"):
            return
        parts = line.split(",")
        if len(parts) != 3:
            return
        try:
            ms, temp_x4, flags = (int(p) for p in parts)
        except ValueError:
            return

        self.last_raw = line
        celsius, reason = decode(temp_x4, flags)
        self.last_reason = reason
        if celsius is None:
            self.n_bad += 1
        else:
            self.n_ok += 1

        now = time.time()
        if self.t0 is None:
            self.t0 = now
        rel = now - self.t0
        self.t.append(rel)
        self.c.append(celsius)
        while self.t and rel - self.t[0] > self.window_s:
            self.t.popleft()
            self.c.popleft()

        if self.csv:
            self.w.writerow([f"{now:.3f}", ms, temp_x4, flags,
                             "" if celsius is None else f"{celsius:.2f}", reason])
            self.csv.flush()

    def close(self):
        if self.csv:
            self.csv.close()


# ---------------------------------------------------------------- terminal
def run_terminal(rec: Recorder):
    """Dependency-free live plot: one column per sample, degC on the left."""
    rows, width = 16, 78
    lo_seen, hi_seen = 1e9, -1e9
    while True:
        vals = [v for v in rec.c if v is not None]
        if vals:
            lo_seen = min(lo_seen, min(vals))
            hi_seen = max(hi_seen, max(vals))
        lo = lo_seen if lo_seen < 1e8 else 0.0
        hi = hi_seen if hi_seen > -1e8 else 1.0
        span = max(hi - lo, 1.0)
        bins = list(rec.c)[-width:]
        grid = [[" "] * width for _ in range(rows)]
        for i, v in enumerate(bins):
            if v is None:
                continue
            r = rows - 1 - int((v - lo) / span * (rows - 1))
            grid[max(0, min(rows - 1, r))][i] = "*"
        out = [f"last: {rec.last_raw!r}  ok={rec.n_ok} bad={rec.n_bad} {rec.last_reason}"]
        for r in range(rows):
            label = f"{hi:6.2f}" if r == 0 else (f"{lo:6.2f}" if r == rows - 1 else " " * 6)
            out.append(f"{label} |{''.join(grid[r])}")
        out.append("       +" + "-" * width)
        sys.stdout.write("\x1b[2J\x1b[H" + "\n".join(out) + "\n")
        sys.stdout.flush()
        time.sleep(0.5)


# ---------------------------------------------------------------- GUI
def run_gui(rec: Recorder, title: str):
    import matplotlib
    matplotlib.use("TkAgg")
    import matplotlib.pyplot as plt

    plt.rcParams["font.sans-serif"] = ["Noto Sans CJK SC", "WenQuanYi Zen Hei",
                                       "DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False

    fig, ax = plt.subplots(figsize=(11, 5))
    ax.set_xlabel("time since start (s)")
    ax.set_ylabel("temperature (°C)")
    ax.set_title(title)
    ax.grid(True, alpha=0.3)
    line, = ax.plot([], [], lw=1.6, color="#1f77b4", label="MAX6675")
    bad_sc, = ax.plot([], [], "x", color="#d62728", ms=7,
                      label="invalid sample (not 0 °C)")
    txt = ax.text(0.01, 0.98, "", transform=ax.transAxes, va="top",
                  family="monospace", fontsize=9,
                  bbox=dict(boxstyle="round", fc="w", ec="0.7", alpha=0.9))
    ax.legend(loc="lower right")
    plt.tight_layout()
    plt.ion()
    plt.show()

    last_draw = 0.0
    while plt.fignum_exists(fig.number):
        now = time.time()
        if now - last_draw >= 0.25 and rec.t:
            ts = list(rec.t)
            cs = list(rec.c)
            xs = [t for t, v in zip(ts, cs) if v is not None]
            ys = [v for v in cs if v is not None]
            bx = [t for t, v in zip(ts, cs) if v is None]
            by = [ys[-1] if ys else 0.0 for _ in bx]
            line.set_data(xs, ys)
            bad_sc.set_data(bx, by)
            if xs:
                ax.set_xlim(max(0.0, ts[-1] - rec.window_s), max(rec.window_s, ts[-1] + 1))
                lo, hi = min(ys), max(ys)
                pad = max(1.0, (hi - lo) * 0.25)
                ax.set_ylim(lo - pad, hi + pad)
            txt.set_text(
                f"last={rec.last_raw or '-'}\n"
                f"ok={rec.n_ok}  invalid={rec.n_bad}"
                + (f"\n{rec.last_reason}" if rec.last_reason else ""))
            fig.canvas.draw_idle()
            plt.pause(0.001)
            last_draw = now
        time.sleep(0.05)


def main() -> int:
    ap = argparse.ArgumentParser()
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--ble", help="BLE address of the transparent bridge")
    src.add_argument("--port", help="serial port, e.g. /dev/ttyUSB0")
    ap.add_argument("--baud", type=int, default=115200)
    ap.add_argument("--csv", default="reader_log.csv", help="where to write the log")
    ap.add_argument("--window", type=float, default=120.0, help="seconds on screen")
    ap.add_argument("--terminal", action="store_true", help="no GUI, ANSI plot")
    args = ap.parse_args()

    rec = Recorder(args.csv, args.window)

    if args.ble:
        thread = BleSource(args.ble, rec.feed)
        thread.start()
    else:
        threading.Thread(target=serial_lines,
                         args=(args.port, args.baud, rec.feed),
                         daemon=True).start()

    print(f"[live] logging to {args.csv}", file=sys.stderr)
    try:
        if args.terminal:
            run_terminal(rec)
        else:
            run_gui(rec, "TC-001 MAX6675 reader" +
                    (f"  ({args.ble})" if args.ble else f"  ({args.port})"))
    except KeyboardInterrupt:
        pass
    finally:
        rec.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
