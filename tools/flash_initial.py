#!/usr/bin/env python3
"""
flash_initial.py - one-time first-time flashing of the STM32F103C8T6.

This is the ONLY step that needs a wired connection (SWD/ST-Link or DAPLink).
It writes the two bundled images:

    bootloader-v0.1.1.bin -> 0x08000000   (12 KB bootloader)
    app-v0.1.38.bin       -> 0x08003000   (IO-console app)

After this, `fwb ota ... --ble <addr>` updates the app wirelessly forever.

The script shells out to STM32_Programmer_CLI (STMicroelectronics, free).
Install "STM32CubeProgrammer" on Windows and make sure the CLI is on PATH,
or pass --programmer with the full path.

Usage:
    python tools/flash_initial.py                       # auto-detect probe
    python tools/flash_initial.py --programmer "C:\\Program Files\\STMicroelectronics\\STM32Cube\\STM32CubeProgrammer\\bin\\STM32_Programmer_CLI.exe"
    python tools/flash_initial.py --port COM5           # serial ISP instead of SWD
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RELEASE = ROOT / "release"

BOOTLOADER = RELEASE / "bootloader-v0.1.1.bin"
APP = RELEASE / "app-v0.1.38.bin"

BL_ADDR = "0x08000000"
APP_ADDR = "0x08003000"

# Common install locations for STM32_Programmer_CLI on Windows.
WINDOWS_CANDIDATES = [
    r"C:\Program Files\STMicroelectronics\STM32Cube\STM32CubeProgrammer\bin\STM32_Programmer_CLI.exe",
    r"C:\Program Files (x86)\STMicroelectronics\STM32Cube\STM32CubeProgrammer\bin\STM32_Programmer_CLI.exe",
]


def find_programmer(explicit: str | None) -> str:
    if explicit:
        p = Path(explicit)
        if not p.exists():
            sys.exit(f"error: --programmer not found: {explicit}")
        return str(p)
    found = shutil.which("STM32_Programmer_CLI") or shutil.which("STM32_Programmer_CLI.exe")
    if found:
        return found
    for c in WINDOWS_CANDIDATES:
        if Path(c).exists():
            return c
    sys.exit(
        "error: STM32_Programmer_CLI not found.\n"
        "  Install STM32CubeProgrammer and/or pass --programmer <path>.\n"
        "  Download: https://www.st.com/en/development-tools/stm32cubeprog.html"
    )


def run(prog: str, args: list[str]) -> None:
    cmd = [prog] + args
    print("  $ " + " ".join(cmd))
    r = subprocess.run(cmd)
    if r.returncode != 0:
        sys.exit(f"error: programmer exited with code {r.returncode}")


def main() -> int:
    ap = argparse.ArgumentParser(description="One-time wired flash of bootloader + app")
    ap.add_argument("--programmer", help="path to STM32_Programmer_CLI(.exe)")
    ap.add_argument("--port", help="serial ISP port (e.g. COM5) instead of SWD/ST-Link")
    ap.add_argument("--skip-erase", action="store_true", help="do not full-chip erase first")
    args = ap.parse_args()

    for f in (BOOTLOADER, APP):
        if not f.exists():
            sys.exit(f"error: missing release artifact: {f}")

    prog = find_programmer(args.programmer)

    # Connection selection: serial ISP (-c port=...) or SWD (-c port=SWD).
    if args.port:
        connect = ["-c", f"port={args.port}"]
        mode = f"serial ISP on {args.port}"
    else:
        connect = ["-c", "port=SWD", "mode=UR"]
        mode = "SWD (ST-Link / DAPLink)"

    print(f"Programmer : {prog}")
    print(f"Connection : {mode}")
    print(f"Bootloader : {BOOTLOADER.name} -> {BL_ADDR}")
    print(f"App        : {APP.name} -> {APP_ADDR}")
    print()

    if not args.skip_erase:
        print("[1/3] erasing chip ...")
        run(prog, connect + ["-e", "all"])
    else:
        print("[1/3] erase skipped")

    print("[2/3] writing bootloader ...")
    run(prog, connect + ["-w", str(BOOTLOADER), BL_ADDR, "-v"])

    print("[3/3] writing app ...")
    run(prog, connect + ["-w", str(APP), APP_ADDR, "-v"])

    print()
    print("Done. Reset the board: PC13 (LED) should blink a 'double-blink'")
    print("heartbeat every 2 s, meaning the app is running.")
    print("Next: connect over BLE and run  fwb info --ble <address>")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
