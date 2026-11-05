"""
test_ota.py - OTA orchestration against a fake bootloader.

The retry policy around BL_DATA is the part of this flow that cannot be got
right by reading the bootloader alone: the command is not idempotent, but the
transport retries by default and the BLE link really does lose ACKs. These
tests pin the two behaviours that matter.

    python -m pytest tests/ -q
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fwb_tool import ota, protocol as P
from fwb_tool.device import DeviceError


@pytest.fixture(autouse=True)
def _no_real_sleep(monkeypatch):
    """The flow sleeps for the app->bootloader reset and for its
    resynchronisation windows; the fake bootloader needs none of that."""
    monkeypatch.setattr(ota.time, "sleep", lambda _s: None)


class FakeBootloader:
    """Device stand-in that models the bootloader's receive/apply rules.

    `drop_ack_at`  - offsets whose response is lost after the write applied
    `chunk_delay`  - no-op, there for readability of the call sites
    """

    def __init__(self, base=0x08003000, max_size=0x1CC00, drop_ack_at=()):
        self.base = base
        self.max_size = max_size
        self.drop_ack_at = set(drop_ack_at)
        self.received = 0
        self.data = bytearray()
        self.expected = 0
        self.started = False
        self.query_count = 0
        self.jumped = False
        self.params = 0
        # The probe phase writes APP_OTA_START straight to the transport when it
        # believes the app is running; a fake bootloader must absorb that.
        self.transport = _Transport()

    # ---- protocol surface used by ota_update ----
    def request(self, cmd, payload=b"", timeout=None, retries=1):
        # BL_VERIFY goes through request(), the rest through request_ok().
        return self._dispatch(cmd, payload)

    def request_ok(self, cmd, payload=b"", timeout=None, retries=1):
        frame = self._dispatch(cmd, payload)
        if frame.status != P.PROTO_OK:
            raise DeviceError(f"cmd 0x{cmd:02X} failed")
        return frame

    def _dispatch(self, cmd, payload):
        if cmd == P.BL_QUERY:
            # The firmware prepends the status byte to every response, so the
            # version block starts at payload[1] (protocol.h: "first payload
            # byte = status").
            self.query_count += 1
            return _Frame(cmd, b"\x00" + bytes([1, 2, 3]) + _u32(self.base) +
                          _u32(self.max_size) + _u32(0x400))
        if cmd == P.BL_START:
            self.expected = int.from_bytes(payload[:4], "big")
            self.received = 0
            self.data = bytearray()
            self.started = True
            return _Frame(cmd, b"\x00")
        if cmd == P.BL_DATA:
            off = int.from_bytes(payload[:4], "big")
            chunk = payload[4:]
            if not self.started or off != self.received:
                self.params += 1
                raise DeviceError(f"cmd 0x{cmd:02X} failed: PARAM")
            self.data += chunk
            self.received += len(chunk)
            if off in self.drop_ack_at:
                raise DeviceError(f"timeout waiting for response to cmd=0x{cmd:02X}")
            return _Frame(cmd, b"\x00")
        if cmd == P.BL_VERIFY:
            want = int.from_bytes(payload[:4], "big")
            got = P.crc32_ieee(bytes(self.data))
            if want != got or self.received != self.expected:
                raise DeviceError(f"cmd 0x{cmd:02X} failed: CRC")
            return _Frame(cmd, b"\x00")
        if cmd == P.BL_JUMP:
            self.jumped = True
            return _Frame(cmd, b"\x00")
        if cmd == P.BL_ABORT:
            # BL_ABORT resets without answering; the host expects a timeout.
            raise DeviceError(f"timeout waiting for response to cmd=0x{cmd:02X}")
        raise AssertionError(f"unexpected cmd 0x{cmd:02X}")

    def ping(self):
        if not self.jumped:
            raise DeviceError("not in app")

    def get_version(self):
        return (1, 2, 3), (0, 1, 44)


class _Frame:
    def __init__(self, cmd, payload):
        self.cmd = cmd
        self.payload = payload

    @property
    def status(self):
        return self.payload[0] if self.payload else -1


class _Transport:
    def write(self, data):
        pass


def _u32(v):
    return v.to_bytes(4, "big")


def _image(size=4096):
    return bytes((i * 7) & 0xFF for i in range(size))


def test_ota_happy_path():
    bl = FakeBootloader()
    result = ota.ota_update(bl, _image())
    assert bl.jumped
    assert bl.received == 4096
    assert result["app"] == (0, 1, 44)


def test_ota_lost_ack_does_not_abort_the_update():
    """A dropped ACK must be treated as "already applied", not as a failure.

    This is the bug that left the board in DFU: the transport re-sent a chunk
    the bootloader had accepted, the bootloader answered PARAM, and the update
    died at a random offset - different on every run."""
    bl = FakeBootloader(drop_ack_at=(1024, 2048))
    ota.ota_update(bl, _image())
    assert bl.jumped
    assert bl.received == 4096
    assert bytes(bl.data) == _image()
    # The PARAM answers are the recovery signal, not an error to surface.
    assert bl.params == 2


def test_ota_rejects_oversize_image_without_erasing():
    bl = FakeBootloader(max_size=1024)
    try:
        ota.ota_update(bl, _image(2048))
    except DeviceError as e:
        assert "partition" in str(e)
    else:
        raise AssertionError("oversize image was accepted")
    assert not bl.started
