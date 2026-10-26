"""
protocol.py - host-side wire protocol for the STM32F103C8T6 OTA tool.

Mirrors firmware/common/protocol.h exactly (frames, CRC, command codes).
fwb_tool/tests/test_protocol.py guards the frozen command-code ABI.

Framing:
    [SOF0][SOF1][CMD][LEN_H][LEN_L][PAYLOAD...][CRC16_H][CRC16_L]
    CRC16-MODBUS covers CMD..end of PAYLOAD.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass

PROTO_SOF0 = 0xAA
PROTO_SOF1 = 0x55
PROTO_MAX_PAYLOAD = 1024

# OTA trigger flag stored in an STM32F1 backup register (16-bit) by the App
# so the bootloader knows to stay in DFU mode after reset.
OTA_MAGIC = 0x4F54  # "OT"

# ---- Bootloader commands (0x01..0x0F) ----
BL_QUERY  = 0x01  # resp: status(1)+bl_ver(3)+app_base(4 BE)+max_size(4 BE)+page(4 BE)
BL_START  = 0x02  # payload: total_len(4B BE)
BL_DATA   = 0x03  # payload: offset(4B BE)+chunk(<=1024)
BL_VERIFY = 0x04  # payload: crc32(4B BE)
BL_JUMP   = 0x05
BL_ABORT  = 0x06

# ---- Application commands (0x10..0x2F) ----
APP_PING          = 0x10
APP_GET_VERSION   = 0x11
APP_REBOOT        = 0x12
APP_OTA_START     = 0x13
APP_GPIO_CONFIG   = 0x14
APP_GPIO_WRITE    = 0x15
APP_GPIO_READ     = 0x16
APP_ADC_READ      = 0x17
APP_PWM_SET       = 0x18
APP_PWM_STOP      = 0x19
APP_GET_TELEMETRY = 0x1A
APP_SET_PARAM     = 0x1B
APP_GET_PARAM     = 0x1C
APP_SET_IO        = 0x1D

APP_TELEMETRY_REPORT = 0x9A  # unsolicited heartbeat / GET_TELEMETRY response

# GPIO modes / pulls (APP_GPIO_CONFIG)
GPIO_MODE_IN, GPIO_MODE_OUT, GPIO_MODE_AF, GPIO_MODE_ANALOG = 0, 1, 2, 3
GPIO_PULL_NONE, GPIO_PULL_UP, GPIO_PULL_DOWN = 0, 1, 2

# Parameter ids
PARAM_HEARTBEAT_MS = 0x01
PARAM_VREF_MV      = 0x02

# Status / error codes
PROTO_OK          = 0x00
PROTO_ERR_GENERIC = 0x01
PROTO_ERR_BUSY    = 0x02
PROTO_ERR_PARAM   = 0x03
PROTO_ERR_CRC     = 0x04
PROTO_ERR_NOAPP   = 0x05
PROTO_ERR_FLASH   = 0x06
PROTO_ERR_MODE    = 0x07

ERR_NAMES = {
    PROTO_OK: "OK",
    PROTO_ERR_GENERIC: "GENERIC",
    PROTO_ERR_BUSY: "BUSY",
    PROTO_ERR_PARAM: "PARAM",
    PROTO_ERR_CRC: "CRC",
    PROTO_ERR_NOAPP: "NOAPP",
    PROTO_ERR_FLASH: "FLASH",
    PROTO_ERR_MODE: "MODE",
}

# Versions (mirror of firmware/common/protocol.h)
BL_VERSION  = (0, 1, 1)
APP_VERSION = (0, 1, 38)


def crc16_modbus(data: bytes) -> int:
    crc = 0xFFFF
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if (crc & 1) else (crc >> 1)
    return crc & 0xFFFF


def crc32_ieee(data: bytes) -> int:
    crc = 0xFFFFFFFF
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = (crc >> 1) ^ 0xEDB88320 if (crc & 1) else (crc >> 1)
    return (crc ^ 0xFFFFFFFF) & 0xFFFFFFFF


def build_frame(cmd: int, payload: bytes = b"") -> bytes:
    if len(payload) > PROTO_MAX_PAYLOAD:
        raise ValueError("payload too long")
    crc_input = bytes([cmd & 0xFF, (len(payload) >> 8) & 0xFF, len(payload) & 0xFF]) + payload
    crc = crc16_modbus(crc_input)
    return (bytes([PROTO_SOF0, PROTO_SOF1, cmd & 0xFF,
                   (len(payload) >> 8) & 0xFF, len(payload) & 0xFF])
            + payload + bytes([crc >> 8, crc & 0xFF]))


@dataclass
class Frame:
    cmd: int
    payload: bytes

    @property
    def status(self) -> int:
        return self.payload[0] if self.payload else -1


class FrameParser:
    """Incremental frame parser: feed() returns complete frames as they arrive."""

    def __init__(self) -> None:
        self._buf = bytearray()

    def feed(self, data: bytes):
        self._buf.extend(data)
        while True:
            frame = self._try_parse()
            if frame is None:
                return
            yield frame

    def _try_parse(self) -> Frame | None:
        buf = self._buf
        while True:
            # resync on SOF pair
            i = 0
            while i < len(buf) - 1 and not (buf[i] == PROTO_SOF0 and buf[i + 1] == PROTO_SOF1):
                i += 1
            if i >= len(buf) - 1:
                if len(buf) > 1:
                    del buf[:-1]   # keep the last byte: it may be a lone SOF0
                return None
            if i > 0:
                del buf[:i]
            if len(buf) < 5:
                return None
            plen = (buf[3] << 8) | buf[4]
            if plen > PROTO_MAX_PAYLOAD:
                del buf[:1]  # false sync; skip one byte and retry
                continue
            total = 5 + plen + 2
            if len(buf) < total:
                return None
            crc_calc = crc16_modbus(bytes(buf[2:5 + plen]))
            crc_rx = (buf[5 + plen] << 8) | buf[5 + plen + 1]
            frame_bytes = bytes(buf[:total])
            del buf[:total]
            if crc_calc != crc_rx:
                continue  # CRC error: drop frame, keep scanning
            return Frame(cmd=frame_bytes[2], payload=frame_bytes[5:5 + plen])


def pack_u32(v: int) -> bytes:
    return struct.pack(">I", v)


def parse_pin(name: str) -> tuple[int, int]:
    """'PA5' -> (0, 5); 'PB12' -> (1, 12); 'PC13' -> (2, 13)."""
    name = name.strip().upper()
    if name.startswith("P"):
        name = name[1:]
    if len(name) < 2 or name[0] not in "ABC" or not name[1:].isdigit():
        raise ValueError(f"bad pin name: {name!r} (expected e.g. PA5)")
    pin = int(name[1:])
    if pin > 15:
        raise ValueError(f"pin number out of range: {name!r}")
    return ("ABC".index(name[0]), pin)


def pin_name(port: int, pin: int) -> str:
    return f"P{'ABC'[port]}{pin}"
