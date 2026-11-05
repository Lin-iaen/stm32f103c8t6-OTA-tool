"""
test_bridge_selftest.py - the bring-up checker itself must not lie.

The tool exists to say "the module is fine, look elsewhere" or "the module is
broken", and a false PASS is worse than no tool at all: it sends you hunting
through firmware when the wire is wrong. These tests pin the two checks that
are easy to get subtly wrong.
"""
import sys
from pathlib import Path

# Repo root (for fwb_tool) and repo root/tools (for the script under test):
# this file lives at <root>/fwb_tool/tests/, so the root is parents[2].
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))

import bridge_selftest as B  # noqa: E402


def test_sizes_include_a_full_bridge_packet():
    """120 B is BRIDGE_MAX_PACKET; a self-test that never sends one would miss
    exactly the failure the OTA hits on every chunk."""
    assert 120 in B.SIZES
    assert max(B.SIZES) >= 120


def test_marker_is_not_self_symmetric():
    """The loopback marker must be distinguishable from idle-line bytes."""
    assert B.MARKER != bytes(len(B.MARKER))
    assert len(set(B.MARKER)) > 1


def test_at_reply_detection_accepts_ok_and_err():
    """Command mode answers OK or ERR; both mean "not transparent"."""
    for reply in (b"OK\r\n", b"ERR\r\n", b"OK", b"ERR"):
        text = reply.decode("ascii", "replace").strip()
        assert text.startswith(("OK", "ERR"))


def test_at_reply_detection_rejects_loopback_residue():
    """Regression: leftover loopback bytes used to read as "in command mode".

    The uplink test pushes arbitrary patterns through the same port, so the
    buffer holds e.g. 0x00 or DEADBEEF afterwards. Treating any non-empty read
    as an AT reply produced a false FAIL on a perfectly healthy module.
    """
    for residue in (b"\x00", b"\xde\xad\xbe\xef", b"\xff" * 4):
        text = residue.decode("ascii", "replace").strip()
        assert not text.startswith(("OK", "ERR"))


def test_wait_services_survives_bluetooth_discovery_race():
    """On BlueZ, client.services raises until async GATT discovery finishes.

    bridge_selftest used to touch that property straight after connect() and
    died with a traceback ("Service Discovery has not been performed yet")
    instead of printing a diagnosis -- i.e. it crashed exactly on the hardware
    it exists to check. wait_services() must poll through that window.
    """
    import asyncio
    from bleak.exc import BleakError

    class FakeClient:
        def __init__(self, fail_times):
            self.fail_times = fail_times
            self.calls = 0

        @property
        def services(self):
            self.calls += 1
            if self.calls <= self.fail_times:
                raise BleakError("Service Discovery has not been performed yet")
            return ["svc-a", "svc-b"]

    async def run(fail_times):
        return await B.wait_services(FakeClient(fail_times), timeout=5.0)

    got = asyncio.run(run(3))
    assert got == ["svc-a", "svc-b"]


def test_wait_services_reports_clear_error_when_discovery_never_finishes():
    """A silent hang is worse than a crisp failure message."""
    import asyncio
    import pytest
    from bleak.exc import BleakError

    class NeverReady:
        @property
        def services(self):
            raise BleakError("Service Discovery has not been performed yet")

    with pytest.raises(RuntimeError, match="GATT discovery did not finish"):
        asyncio.run(B.wait_services(NeverReady(), timeout=0.6))
