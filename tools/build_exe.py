#!/usr/bin/env python3
"""
build_exe.py - build a standalone single-file `fwb` executable with PyInstaller.

Run this ON WINDOWS to get `dist/fwb.exe` (PyInstaller does not cross-compile).
On Linux/macOS it produces a native binary of the same name.

    pip install -e ".[dev]"
    python tools/build_exe.py

The resulting dist/fwb.exe bundles Python, pyserial and bleak, so the target
machine needs neither Python nor pip. BLE still needs a working Bluetooth
adapter and (on Windows) Windows 10 1703 or newer.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        sys.exit('error: PyInstaller missing. Run: pip install -e ".[dev]"')

    args = [
        sys.executable, "-m", "PyInstaller",
        "--onefile",
        "--name", "fwb",
        "--clean",
        "--noconfirm",
        # bleak pulls in platform backends via dynamic imports; collect them all.
        "--collect-all", "bleak",
        "--collect-all", "bleak_winrt",
        "--hidden-import", "serial",
        "--hidden-import", "serial.tools.list_ports",
        str(ROOT / "fwb_tool" / "cli.py"),
    ]
    print("$ " + " ".join(args))
    r = subprocess.run(args, cwd=ROOT)
    if r.returncode != 0:
        return r.returncode

    exe = "fwb.exe" if sys.platform == "win32" else "fwb"
    print(f"\nBuilt: {ROOT / 'dist' / exe}")
    print("Copy it anywhere and run:  fwb scan-ble")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
