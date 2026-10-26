"""
cli.py - fwb command line tool (cross-platform: Linux / macOS / Windows).

Primary use (wireless OTA):

    fwb scan-ble [--timeout 5]                   scan BLE adverts
    fwb info  --ble ADDR                         ping + read versions
    fwb ota   app.bin --ble ADDR                 wireless firmware update

Wired alternatives (USB-TTL adapter, or a BT-SPP module exposed as a COM port):

    fwb scan-serial                              list serial ports
    fwb info  --port COM5                        ping + read versions
    fwb ota   app.hex --port COM5                firmware update over serial

Extra commands for the IO-console firmware:

    fwb monitor [--n 0] [--port ...] [--ble ...] live telemetry (0 = forever)
    fwb gpio config PA5 out|in|af|analog [up|down]
    fwb gpio write PA5 1 | fwb gpio read PB3
    fwb adc read 0..17
    fwb pwm set CH FREQ_HZ DUTY_PERMILLE | fwb pwm stop CH
    fwb param get ID | fwb param set ID VALUE
    fwb led on|off
    fwb reboot
"""
from __future__ import annotations

import argparse
import sys
import time

from . import protocol as P
from .device import Device, DeviceError, Telemetry, load_image
from .ota import ota_update
from .transport import TransportError, scan_label, scan_serial, scan_ble


def _open_device(args, on_telemetry=None) -> Device:
    if args.ble:
        return Device.open_ble(args.ble, on_telemetry)
    if args.port:
        return Device.open_serial(args.port, getattr(args, "baud", 115200), on_telemetry)
    raise SystemExit("error: specify --ble <address> or --port <serial port> (e.g. COM5)")


def _common(parser):
    parser.add_argument("--port", help="serial port (e.g. COM5 on Windows, /dev/ttyUSB0 on Linux)")
    parser.add_argument("--ble", help="BLE device address from scan-ble")
    parser.add_argument("--baud", type=int, default=115200)


# ---------------- subcommands ----------------

def cmd_scan_serial(_args):
    ports = scan_serial()
    if not ports:
        print("no serial ports found")
        return
    for dev, desc in ports:
        print(f"{dev:20s} {desc}")


def cmd_scan_ble(args):
    print(f"scanning BLE for {args.timeout}s ...")
    rows = scan_ble(args.timeout, args.service)
    for addr, name, services in rows:
        print(f"{addr:20s} {scan_label(name, services)}")
    if rows and not any(name for _addr, name, _services in rows):
        print("\n(no device advertises a name; {uuid} is the first advertised "
              "service. Narrow the list with --service 0000ffe0-...)")


def cmd_info(args):
    with _open_device(args) as dev:
        dev.ping()
        bl, app = dev.get_version()
        print(f"connected. bootloader v{'.'.join(map(str, bl))}, app v{'.'.join(map(str, app))}")


def cmd_ota(args):
    image = load_image(args.image)
    print(f"image: {args.image} ({len(image)} bytes)")

    last = {"phase": None, "pct": -1}

    def progress(phase, pct, msg=""):
        if pct > last["pct"] or phase != last["phase"]:
            bar = "#" * (pct // 4)
            print(f"[{phase:>6}] {pct:3d}% {bar:<25s} {msg}")
            last["phase"], last["pct"] = phase, pct

    with _open_device(args) as dev:
        result = ota_update(dev, image, progress)
    print(f"OTA complete: app v{'.'.join(map(str, result['app']))}")


def _monitor_ticks(n: int):
    """Yield once per second of listening. n == 0 means "forever".

    `--n` is a duration, not a report count: the device paces telemetry with
    heartbeat_ms, so the number of frames printed for a given duration depends
    on that parameter. Kept as a generator so `--n 3` cannot fall back into the
    endless branch when the counter reaches 0 (the bug in the old loop).
    """
    count = 0
    while n == 0 or count < n:
        yield count
        count += 1


def cmd_monitor(args):
    def show(t: Telemetry):
        up = t.uptime_ms / 1000
        vbat = f"{t.vbat_mv:5d}mV" if t.vbat_valid else "  ----mV (ADC invalid)"
        print(f"uptime={up:8.1f}s  vbat={vbat}  pwm={'ON' if t.pwm_active else 'off'}")

    with _open_device(args, on_telemetry=show) as dev:
        # force one report immediately
        try:
            show(dev.read_telemetry())
        except Exception:
            pass
        for _ in _monitor_ticks(args.n):
            time.sleep(1.0)
        # BLE disconnect takes a couple of seconds and notifications keep
        # arriving until it completes; without this, `--n 5` printed 6-7
        # lines. Reports are counted, so stop printing once the count is met.
        dev.on_telemetry = None


def cmd_gpio(args):
    port, pin = P.parse_pin(args.pin)
    with _open_device(args) as dev:
        if args.op == "config":
            mode = {"in": P.GPIO_MODE_IN, "out": P.GPIO_MODE_OUT,
                    "af": P.GPIO_MODE_AF, "analog": P.GPIO_MODE_ANALOG}[args.mode]
            pull = {"none": P.GPIO_PULL_NONE, "up": P.GPIO_PULL_UP,
                    "down": P.GPIO_PULL_DOWN}[args.pull]
            dev.request_ok(P.APP_GPIO_CONFIG, bytes([port, pin, mode, pull]))
            print(f"{args.pin} configured: {args.mode} (pull {args.pull})")
        elif args.op == "write":
            val = 1 if args.value in ("1", "on", "high") else 0
            dev.request_ok(P.APP_GPIO_WRITE, bytes([port, pin, val]))
            print(f"{args.pin} <- {val}")
        elif args.op == "read":
            f = dev.request_ok(P.APP_GPIO_READ, bytes([port, pin]))
            print(f"{args.pin} = {f.payload[1]}")


def cmd_adc(args):
    with _open_device(args) as dev:
        f = dev.request_ok(P.APP_ADC_READ, bytes([args.channel]))
        mv = int.from_bytes(f.payload[1:3], "big")
        print(f"ADC ch{args.channel} = {mv} mV")


def cmd_pwm(args):
    with _open_device(args) as dev:
        if args.op == "set":
            if not (0 <= args.ch <= 7):
                raise SystemExit("channel must be 0..7")
            dev.request_ok(P.APP_PWM_SET,
                           bytes([args.ch]) + P.pack_u32(args.freq) +
                           args.duty.to_bytes(2, "big"))
            print(f"PWM ch{args.ch}: {args.freq} Hz @ {args.duty/10:.1f}%")
        else:
            dev.request_ok(P.APP_PWM_STOP, bytes([args.ch]))
            print(f"PWM ch{args.ch} stopped")


def cmd_param(args):
    with _open_device(args) as dev:
        if args.op == "get":
            f = dev.request_ok(P.APP_GET_PARAM, bytes([args.pid]))
            v = int.from_bytes(f.payload[1:5], "big")
            print(f"param 0x{args.pid:02X} = {v}")
        else:
            dev.request_ok(P.APP_SET_PARAM, bytes([args.pid]) + P.pack_u32(args.value))
            print(f"param 0x{args.pid:02X} = {args.value}")


def cmd_led(args):
    with _open_device(args) as dev:
        dev.request_ok(P.APP_SET_IO, bytes([1 if args.on else 0, 0, 0]))
        print(f"LED {'on' if args.on else 'off'}")


def cmd_reboot(args):
    with _open_device(args) as dev:
        dev.request_ok(P.APP_REBOOT)
        print("rebooting")


# ---------------- parser ----------------

def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="fwb", description="f103-workbench CLI")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("scan-serial", help="list serial ports").set_defaults(fn=cmd_scan_serial)

    p = sub.add_parser("scan-ble", help="scan BLE adverts")
    p.add_argument("--timeout", type=float, default=5.0)
    p.add_argument("--service", help="filter by advertised service UUID (e.g. 0000ffe0-...)")
    p.set_defaults(fn=cmd_scan_ble)

    p = sub.add_parser("info", help="ping + read versions")
    _common(p); p.set_defaults(fn=cmd_info)

    p = sub.add_parser("ota", help="wireless firmware update")
    p.add_argument("image", help="app.bin or app.hex")
    _common(p); p.set_defaults(fn=cmd_ota)

    p = sub.add_parser("monitor", help="live telemetry")
    p.add_argument("--n", type=int, default=0,
                   help="listen for N seconds (0 = forever); one report per heartbeat")
    _common(p); p.set_defaults(fn=cmd_monitor)

    p = sub.add_parser("gpio", help="gpio config/write/read")
    p.add_argument("op", choices=["config", "write", "read"])
    p.add_argument("pin", help="pin name like PA5")
    p.add_argument("rest", nargs="*", help="mode/pull or value")
    _common(p)

    def gpio_wrap(args):
        if args.op == "config":
            if not args.rest:
                raise SystemExit("usage: fwb gpio config PA5 out|in|af|analog [up|down]")
            args.mode = args.rest[0]
            args.pull = args.rest[1] if len(args.rest) > 1 else "none"
        elif args.op == "write":
            if not args.rest:
                raise SystemExit("usage: fwb gpio write PA5 1")
            args.value = args.rest[0]
        cmd_gpio(args)
    p.set_defaults(fn=gpio_wrap)

    p = sub.add_parser("adc", help="read ADC channel")
    p.add_argument("op", choices=["read"])
    p.add_argument("channel", type=int)
    _common(p); p.set_defaults(fn=cmd_adc)

    p = sub.add_parser("pwm", help="pwm set/stop")
    p.add_argument("op", choices=["set", "stop"])
    p.add_argument("ch", type=int)
    p.add_argument("rest", nargs="*", help="freq duty for set")
    _common(p)

    def pwm_wrap(args):
        if args.op == "set":
            if len(args.rest) != 2:
                raise SystemExit("usage: fwb pwm set CH FREQ_HZ DUTY_PERMILLE (0..1000)")
            args.freq, args.duty = int(args.rest[0]), int(args.rest[1])
        cmd_pwm(args)
    p.set_defaults(fn=pwm_wrap)

    p = sub.add_parser("param", help="get/set runtime param")
    p.add_argument("op", choices=["get", "set"])
    p.add_argument("pid", type=lambda s: int(s, 0))
    p.add_argument("value", nargs="?", type=int)
    _common(p)

    def param_wrap(args):
        if args.op == "set" and args.value is None:
            raise SystemExit("usage: fwb param set ID VALUE")
        cmd_param(args)
    p.set_defaults(fn=param_wrap)

    p = sub.add_parser("led", help="board LED (PC13)")
    p.add_argument("state", choices=["on", "off"])
    _common(p)

    def led_wrap(args):
        args.on = args.state == "on"
        cmd_led(args)
    p.set_defaults(fn=led_wrap)

    p = sub.add_parser("reboot", help="reset the device")
    _common(p); p.set_defaults(fn=cmd_reboot)

    return ap


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        args.fn(args)
        return 0
    except (DeviceError, TransportError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
