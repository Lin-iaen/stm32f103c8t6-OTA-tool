"""fwb - STM32F103C8T6 wireless OTA tool.

Host side of the f103-workbench OTA protocol: frame codec, serial/BLE
transports, device request/response layer, and the OTA orchestration.

Usage:
    from fwb_tool import Device, ota_update

    with Device.open_ble("AA:BB:CC:DD:EE:FF") as dev:
        ota_update(dev, open("app.bin", "rb").read())

Derived from kurui365/smart-robot-car (MIT). See ATTRIBUTION.md.
"""

__version__ = "0.1.0"

from .device import Device, DeviceError, Telemetry, load_image  # noqa: F401
from .ota import ota_update  # noqa: F401
