"""
ota.py - wireless firmware upgrade orchestration.

Flow inherited from smart-robot-car (serial_comm.py, MIT), transport-agnostic:

    probe BL_QUERY ─┬─ already in bootloader
                    └─ in App -> APP_OTA_START(total_len) -> reset
    BL_QUERY  -> app_base / max_size / page size
    BL_START  -> sets in-progress flag + erases app region
    BL_DATA   -> sequential even-offset chunks (512 B)
    BL_VERIFY -> stream CRC32 == flash CRC32 == host CRC32
    BL_JUMP   -> clears flag, jumps; host re-pings the new App

Anti-brick properties (bootloader side):
    - erase happens only after the flag is set, so power loss mid-update
      leaves the bootloader in DFU mode on next boot
    - jump is allowed only after a successful verify (or with no flag set)
"""
from __future__ import annotations

import time

from .protocol import (
    BL_QUERY, BL_START, BL_DATA, BL_VERIFY, BL_JUMP,
    APP_OTA_START, APP_PING, APP_GET_VERSION,
    PROTO_OK, crc32_ieee, pack_u32,
)
from .device import Device, DeviceError

CHUNK = 512                 # even, <=1024; matches BL_DATA constraints
BL_QUERY_TIMEOUT = 3.0      # bootloader needs a beat to come up after reset
APP_RESET_WAIT = 1.5


def _status(f):
    return f.payload[0] if f.payload else -1


def ota_update(dev: Device, image: bytes, progress=None, verify_retries: int = 2) -> dict:
    """Flash `image` (raw bytes linked at app_base) over the open transport.

    progress(phase, pct, msg): phase in probe|erase|write|verify|jump|done.
    Returns {'bl': (maj,min,pat), 'app': (maj,min,pat)} of the NEW app."""
    def emit(phase, pct, msg=""):
        if progress:
            progress(phase, pct, msg)

    # Pad to even length: flash writes are 16-bit; the final BL_DATA chunk
    # may be odd only if it completes the image -- padding keeps every chunk
    # even and the device-side CRC stream identical to what we compute here.
    if len(image) % 2:
        image = image + b"\xFF"

    total = len(image)
    image_crc = crc32_ieee(image)

    # ---------- 1) probe: are we already in the bootloader? ----------
    emit("probe", 1)
    in_bl = False
    try:
        f = dev.request(BL_QUERY, timeout=1.0, retries=0)
        in_bl = (_status(f) == PROTO_OK and len(f.payload) >= 15)
    except DeviceError:
        in_bl = False

    if not in_bl:
        emit("probe", 3, "triggering OTA start (App resets into bootloader)")
        # Fire-and-forget: the App answers OK then resets; the connection
        # briefly dies, so do not wait for the response.
        from .protocol import build_frame
        dev.transport.write(build_frame(APP_OTA_START, pack_u32(total)))
        time.sleep(APP_RESET_WAIT)

    # ---------- 2) BL_QUERY (with retries while the BL boots) ----------
    q = None
    last: Exception | None = None
    for _ in range(3):
        try:
            f = dev.request(BL_QUERY, timeout=BL_QUERY_TIMEOUT, retries=0)
            if _status(f) == PROTO_OK and len(f.payload) >= 15:
                q = f.payload
                break
        except DeviceError as e:
            last = e
        time.sleep(0.6)
    if q is None:
        raise DeviceError(f"bootloader did not answer BL_QUERY: {last}")

    bl_ver = (q[1], q[2], q[3])
    app_base = int.from_bytes(q[4:8], "big")
    max_size = int.from_bytes(q[8:12], "big")
    if total > max_size:
        raise DeviceError(f"image {total}B > partition {max_size}B (base 0x{app_base:08X})")

    # ---------- 3) BL_START: flag + erase ----------
    emit("erase", 2, f"erasing {max_size//1024} KB app region")
    dev.request_ok(BL_START, pack_u32(total), timeout=10.0)

    # ---------- 4) BL_DATA ----------
    off = 0
    while off < total:
        chunk = image[off:off + CHUNK]
        payload = pack_u32(off) + chunk
        dev.request_ok(BL_DATA, payload, timeout=5.0)
        off += len(chunk)
        emit("write", 3 + int(87 * off / total),
             f"{off}/{total} bytes")

    # ---------- 5) BL_VERIFY ----------
    emit("verify", 92, f"CRC32 0x{image_crc:08X}")
    v = None
    for attempt in range(verify_retries + 1):
        try:
            v = dev.request(BL_VERIFY, pack_u32(image_crc), timeout=5.0)
            break
        except DeviceError:
            if attempt == verify_retries:
                raise
        time.sleep(0.3)
    if _status(v) != PROTO_OK:
        from .protocol import ERR_NAMES
        raise DeviceError(f"verify failed: {ERR_NAMES.get(_status(v))}")

    # ---------- 6) BL_JUMP ----------
    emit("jump", 96)
    try:
        dev.request(BL_JUMP, timeout=3.0, retries=0)
    except DeviceError:
        pass   # response may be eaten by the jump itself
    time.sleep(1.0)

    # ---------- 7) confirm the new App ----------
    for _ in range(5):
        try:
            dev.ping()
            ver = dev.get_version()
            emit("done", 100, f"App now {ver[1]}")
            return {"bl": ver[0], "app": ver[1]}
        except DeviceError:
            time.sleep(0.5)
    raise DeviceError("device did not come back after jump (try `fwb info`)")
