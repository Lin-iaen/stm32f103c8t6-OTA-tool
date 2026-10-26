"""
test_protocol.py - protocol regression: frame math, parser robustness,
CRC compatibility, image loading, and pin naming.

Run: python -m pytest fwb_tool/tests/ -q

These tests encode the wire contract between the device firmware
(firmware/common/protocol.h) and this host tool. The command-code values
below are the frozen ABI: do not change them without a matching firmware
release, and keep this file in sync with host/fwb/protocol.py in the
f103-workbench source tree.
"""
import struct
from pathlib import Path

from fwb_tool import protocol as P
from fwb_tool.device import load_image, parse_telemetry, DeviceError
from fwb_tool.transport import (
    ATT_MIN_PAYLOAD,
    BRIDGE_MAX_PACKET,
    _is_length_error,
    plan_chunk_size,
)


# ---------------- CRC reference vectors ----------------

def test_crc16_modbus_known_vector():
    # Standard MODBUS check value for "123456789" (ASCII)
    assert P.crc16_modbus(b"123456789") == 0x4B37


def test_crc32_ieee_known_vector():
    # Standard CRC-32 check value for "123456789"
    assert P.crc32_ieee(b"123456789") == 0xCBF43926


# ---------------- frame build/parse round trip ----------------

def test_frame_round_trip_all_payload_sizes():
    for n in (0, 1, 2, 7, 1024):
        payload = bytes((i * 31) & 0xFF for i in range(n))
        for cmd in (P.APP_PING, P.BL_DATA, 0x9A):
            frame = P.build_frame(cmd, payload)
            assert frame[0] == 0xAA and frame[1] == 0x55
            assert frame[2] == cmd
            assert len(frame) == 7 + n
            parser = P.FrameParser()
            got = list(parser.feed(frame))
            assert len(got) == 1
            assert got[0].cmd == cmd
            assert got[0].payload == payload


def test_frame_crc_covers_cmd_to_payload():
    # CRC must be over CMD+LEN+PAYLOAD (not SOF), big-endian, high byte first.
    payload = b"\x01\x02"
    frame = P.build_frame(P.APP_GPIO_WRITE, payload)
    crc = P.crc16_modbus(bytes([P.APP_GPIO_WRITE, 0, 2]) + payload)
    assert frame[-2] == crc >> 8
    assert frame[-1] == crc & 0xFF


def test_response_cmd_is_or80():
    # A response echoes cmd|0x80: firmware dispatch sends (cmd|0x80).
    assert P.APP_GET_TELEMETRY | 0x80 == P.APP_TELEMETRY_REPORT
    assert P.BL_QUERY | 0x80 == 0x81


# ---------------- parser robustness ----------------

def test_parser_resync_after_garbage():
    good = P.build_frame(P.APP_PING)
    stream = b"\x00\xDE\xAD" + good + b"\xBE\xEF" + good
    parser = P.FrameParser()
    frames = list(parser.feed(stream))
    assert len(frames) == 2
    assert all(f.cmd == P.APP_PING for f in frames)


def test_parser_splits_joined_frames():
    f1 = P.build_frame(P.APP_PING)
    f2 = P.build_frame(P.BL_QUERY, b"")
    parser = P.FrameParser()
    got = list(parser.feed(f1 + f2))
    assert [f.cmd for f in got] == [P.APP_PING, P.BL_QUERY]


def test_parser_handles_partial_feeds():
    frame = P.build_frame(P.APP_ADC_READ, b"\x05")
    parser = P.FrameParser()
    out = []
    for i in range(len(frame)):
        out += list(parser.feed(frame[i:i + 1]))
    assert len(out) == 1 and out[0].payload == b"\x05"


def test_parser_drops_corrupted_crc():
    frame = bytearray(P.build_frame(P.APP_PING, b"\xAA"))
    frame[-1] ^= 0xFF   # break CRC
    parser = P.FrameParser()
    assert list(parser.feed(bytes(frame + P.build_frame(P.APP_PING)))) != []


def test_parser_rejects_oversized_len():
    # LEN=0xFFFF > 1024 must not allocate/copy, must resync eventually.
    frame = bytes([0xAA, 0x55, 0x10, 0xFF, 0xFF]) + b"\x00\x00"
    parser = P.FrameParser()
    good = P.build_frame(P.APP_PING)
    got = list(parser.feed(frame + good))
    assert [f.cmd for f in got] == [P.APP_PING]


# ---------------- frozen command-code ABI ----------------
# These literals are the contract with firmware/common/protocol.h. If a test
# here fails, the host and the released bootloader/app disagree.

def test_command_codes_frozen():
    assert (P.BL_QUERY, P.BL_START, P.BL_DATA,
            P.BL_VERIFY, P.BL_JUMP, P.BL_ABORT) == (0x01, 0x02, 0x03, 0x04, 0x05, 0x06)
    assert (P.APP_PING, P.APP_GET_VERSION, P.APP_REBOOT, P.APP_OTA_START) == (0x10, 0x11, 0x12, 0x13)
    assert (P.APP_GPIO_CONFIG, P.APP_GPIO_WRITE, P.APP_GPIO_READ) == (0x14, 0x15, 0x16)
    assert (P.APP_ADC_READ, P.APP_PWM_SET, P.APP_PWM_STOP) == (0x17, 0x18, 0x19)
    assert (P.APP_GET_TELEMETRY, P.APP_SET_PARAM, P.APP_GET_PARAM, P.APP_SET_IO) == (0x1A, 0x1B, 0x1C, 0x1D)
    assert P.APP_TELEMETRY_REPORT == 0x9A
    assert (P.PARAM_HEARTBEAT_MS, P.PARAM_VREF_MV) == (0x01, 0x02)


def test_ota_magic_fits_backup_register():
    # Firmware stores OTA_MAGIC in a 16-bit STM32F1 BKP_DRx.
    assert P.OTA_MAGIC == 0x4F54
    assert P.OTA_MAGIC <= 0xFFFF


# ---------------- BLE chunk planning ----------------

def test_plan_chunk_size():
    # WinRT: MTU 136 -> 133; BlueZ 5.62+: MTU 517 -> 514. Both cap at 120.
    assert plan_chunk_size(133) == BRIDGE_MAX_PACKET
    assert plan_chunk_size(514) == BRIDGE_MAX_PACKET
    # A genuinely small MTU is respected.
    assert plan_chunk_size(64) == 64
    # 20/23 are bleak's "unknown MTU" markers, not a real 23-byte MTU.
    assert plan_chunk_size(23) == BRIDGE_MAX_PACKET
    assert plan_chunk_size(20) == BRIDGE_MAX_PACKET
    assert plan_chunk_size(None) == BRIDGE_MAX_PACKET
    assert BRIDGE_MAX_PACKET % 2 == 0          # BL_DATA wants even chunks
    assert ATT_MIN_PAYLOAD == 20


def test_is_length_error():
    assert _is_length_error(Exception("WinError -2147024809"))
    assert _is_length_error(Exception("[org.bluez.Error.Failed] Failed to initiate write"))
    assert _is_length_error(Exception("InvalidValueLength"))
    assert not _is_length_error(Exception("Not connected"))


# ---------------- telemetry ----------------

def test_telemetry_parse():
    t = parse_telemetry(struct.pack(">IHB", 123456, 3300, 1))
    assert t.uptime_ms == 123456
    assert t.vbat_mv == 3300
    assert t.pwm_active
    assert t.vbat_valid


def test_telemetry_marks_failed_adc_read():
    """flags bit1 = "vbat invalid"; 0 mV must not look like a measurement."""
    t = parse_telemetry(struct.pack(">IHB", 1000, 0, 0x02))
    assert t.vbat_mv == 0
    assert not t.vbat_valid
    assert not t.pwm_active


# ---------------- image loading ----------------

def test_load_bin_image():
    import tempfile
    blob = bytes(range(256)) * 4
    with tempfile.NamedTemporaryFile(suffix=".bin", delete=False) as f:
        f.write(blob)
        path = f.name
    try:
        assert load_image(path) == blob
    finally:
        Path(path).unlink(missing_ok=True)


def test_load_ihex_image(tmp_path):
    # 16 bytes at app_base in Intel HEX (ext-linear-address + data records).
    base = 0x08003000
    data = bytes(range(16))
    rec_ext = _ihex(0x04, 0x0000, (base >> 16).to_bytes(2, "big"))
    rec_data = _ihex(0x00, base & 0xFFFF, data)
    f = tmp_path / "app.hex"
    f.write_text(rec_ext + "\n" + rec_data + "\n" + _ihex(0x01, 0x0000) + "\n")
    assert load_image(str(f)) == data


def _ihex(rectype: int, addr: int, payload: bytes = b"") -> str:
    body = bytes([len(payload), (addr >> 8) & 0xFF, addr & 0xFF, rectype]) + payload
    s = sum(body) & 0xFF
    body += bytes([(0x100 - s) & 0xFF])
    return ":" + body.hex().upper()


def test_load_image_rejects_oversize():
    import tempfile
    with tempfile.NamedTemporaryFile(suffix=".bin", delete=False) as f:
        f.write(b"\x00" * (0x1CC00 + 1))
    try:
        try:
            load_image(f.name)
            assert False, "should have raised"
        except DeviceError:
            pass
    finally:
        Path(f.name).unlink(missing_ok=True)


# ---------------- pin naming ----------------

def test_parse_pin():
    assert P.parse_pin("PA0") == (0, 0)
    assert P.parse_pin("pb12") == (1, 12)
    assert P.parse_pin("PC13") == (2, 13)
    assert P.parse_pin("A5") == (0, 5)   # 'P' prefix optional
    for bad in ("PZ3", "PA16", "", "P"):
        try:
            P.parse_pin(bad)
            assert False
        except ValueError:
            pass


# ---------------- CLI / diagnostics regressions ----------------

def test_monitor_ticks_stops_after_n():
    """`fwb monitor --n 3` must exit; the old loop fell back to "forever"."""
    from fwb_tool.cli import _monitor_ticks
    assert list(_monitor_ticks(3)) == [0, 1, 2]


def test_monitor_ticks_zero_means_forever():
    from itertools import islice
    from fwb_tool.cli import _monitor_ticks
    assert list(islice(_monitor_ticks(0), 5)) == [0, 1, 2, 3, 4]


def test_scan_label_shows_services_when_name_missing():
    from fwb_tool.transport import scan_label
    assert scan_label("JDY-31-SPP", []) == "JDY-31-SPP"
    assert scan_label(None, ["0000ffe0-0000-1000-8000-00805f9b34fb"]) == "{ffe0}"
    assert scan_label(None, ["0000ffe0-0000-1000-8000-00805f9b34fb",
                             "0000ffe1-0000-1000-8000-00805f9b34fb"]) == "{ffe0,ffe1}"
    assert scan_label(None, []) == "?"


def test_connect_error_keeps_exception_type_when_str_is_empty():
    """WinRT HRESULT errors can have an empty str(); the message must not be."""
    from fwb_tool.transport import _connect_error_message

    class EmptyError(Exception):
        def __str__(self):
            return ""

    msg = _connect_error_message("AA:BB:CC:DD:EE:FF", EmptyError())
    assert "AA:BB:CC:DD:EE:FF" in msg
    assert "EmptyError" in msg
    assert msg.rstrip().endswith("EmptyError()")
