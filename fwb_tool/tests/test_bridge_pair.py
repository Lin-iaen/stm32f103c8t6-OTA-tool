"""
test_bridge_pair.py - which GATT characteristic is the serial pipe.

A transparent BLE bridge exposes one serial pipe, but vendors model it in two
different ways and the difference is invisible until an OTA stalls:

  combined  one characteristic carries both directions (JDY-69, HC-08)
            -> write and notify must be THE SAME characteristic
  split     separate downlink/uplink characteristics (VG6328A/I6328A)
            -> write and notify MUST DIFFER

The topology fixtures below are copied from real devices, not invented:
`JDY69_ON_BENCH` is the dump taken off the module on this bench, and
`VG6328A` is section 5 of the Vollgo VG6328A datasheet (FFE1 write-without-
response / FFE2 notify).

    python -m pytest tests/ -q
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fwb_tool.transport import pick_bridge_pair

FFE1 = "0000ffe1-0000-1000-8000-00805f9b34fb"
FFE2 = "0000ffe2-0000-1000-8000-00805f9b34fb"
FF11 = "0000ff11-0000-1000-8000-00805f9b34fb"
FF12 = "0000ff12-0000-1000-8000-00805f9b34fb"
SVC_FFE0 = "0000ffe0-0000-1000-8000-00805f9b34fb"
SVC_FF10 = "0000ff10-0000-1000-8000-00805f9b34fb"


class Ch:
    """Stand-in for bleak's BleakGATTCharacteristic."""

    def __init__(self, uuid, properties, service_uuid=None, max_write=20):
        self.uuid = uuid
        self.properties = properties
        self.service_uuid = service_uuid
        self.max_write_without_response_size = max_write

    def __repr__(self):
        return f"Ch({self.uuid[4:8]})"


def short(ch):
    return ch.uuid[4:8] if ch else None


# ---------------------------------------------------------------- fixtures

def jdy69_on_bench():
    """Ground truth dumped from the JDY-69 connected to this bench.

    Both characteristics in ffe0 support write+notify, and ff10 exposes a
    second such pair. The serial pipe has always been ffe1 - that choice must
    not change now that the selection logic is shared.
    """
    return [
        Ch(FFE2, ["write-without-response", "notify"], SVC_FFE0),
        Ch(FFE1, ["write-without-response", "notify"], SVC_FFE0),
        Ch(FF12, ["write-without-response", "notify"], SVC_FF10),
        Ch(FF11, ["write-without-response", "notify"], SVC_FF10),
    ]


def vg6328a():
    """Vollgo VG6328A / I6328A, datasheet section 5.

    FFE1 is Write Without Response only, FFE2 is Notify only.
    """
    return [
        Ch(FFE1, ["write-without-response"], SVC_FFE0),
        Ch(FFE2, ["notify"], SVC_FFE0),
    ]


# ---------------------------------------------------------------- combined

def test_jdy69_still_selects_ffe1_for_both_directions():
    """Regression: the module on the bench must keep working unchanged."""
    w, n = pick_bridge_pair(jdy69_on_bench())
    assert short(w) == "ffe1"
    assert short(n) == "ffe1"
    assert w is n, "combined layout must reuse one characteristic"


def test_combined_layout_ignores_the_second_service():
    """ff10/ff11/ff12 is a config channel; it must not win over ffe0."""
    w, _n = pick_bridge_pair(jdy69_on_bench())
    assert w.service_uuid == SVC_FFE0


# ---------------------------------------------------------------- split

def test_vg6328a_split_layout_pairs_ffe1_with_ffe2():
    w, n = pick_bridge_pair(vg6328a())
    assert short(w) == "ffe1", "FFE1 is the downlink (Write Without Response)"
    assert short(n) == "ffe2", "FFE2 is the uplink (Notify)"
    assert w is not n


def test_split_layout_does_not_return_none():
    """The bug this file exists for: requiring one characteristic to do both
    made the split layout return (None, None), which every caller reports as
    "module not compatible" when the module is in fact fine."""
    w, n = pick_bridge_pair(vg6328a())
    assert w is not None and n is not None


def test_split_pairing_stays_inside_one_service():
    """Two look-alike services must not be cross-paired.

    If downlink came from ffe0 and uplink from ff10 the link would look
    connected and carry nothing, which is worse than failing.
    """
    chars = [
        Ch(FFE1, ["write-without-response"], SVC_FFE0),
        Ch(FFE2, ["notify"], SVC_FFE0),
        Ch(FF12, ["write-without-response"], SVC_FF10),
        Ch(FF11, ["notify"], SVC_FF10),
    ]
    w, n = pick_bridge_pair(chars)
    assert w.service_uuid == SVC_FFE0
    assert n.service_uuid == SVC_FFE0
    assert (short(w), short(n)) == ("ffe1", "ffe2")


# ---------------------------------------------------------------- degenerate

def test_no_notify_characteristic_returns_none():
    w, n = pick_bridge_pair([Ch(FFE1, ["write-without-response"], SVC_FFE0)])
    assert (w, n) == (None, None)


def test_no_write_characteristic_returns_none():
    w, n = pick_bridge_pair([Ch(FFE2, ["notify"], SVC_FFE0)])
    assert (w, n) == (None, None)


def test_empty_device_returns_none():
    assert pick_bridge_pair([]) == (None, None)


def test_unknown_custom_uuids_still_pair():
    """Vendors allow custom UUIDs; the well-known list is a preference, not a
    requirement."""
    w, n = pick_bridge_pair([
        Ch("12345678-1234-5678-1234-56789abcdef1", ["write", "notify"], "custom"),
    ])
    assert w is not None and n is not None
