"""The KingSmith WalkingPad A1 integration.

Drives the pad over Bluetooth Low Energy through Home Assistant's Bluetooth
stack. Because connections go through HA, they are routed over whatever
adapter can reach the pad, including an ESP32 Bluetooth proxy in active mode,
so no dedicated bridge board is required.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from homeassistant.components import bluetooth
from homeassistant.components.bluetooth import (
    BluetoothCallbackMatcher,
    BluetoothChange,
    BluetoothScanningMode,
    BluetoothServiceInfoBleak,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ADDRESS, Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryNotReady

from .const import DOMAIN
from .coordinator import WalkingPadCoordinator
from .walkingpad import TRANSIENT_ERRORS, WalkingPadTreadmill

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.BUTTON, Platform.NUMBER, Platform.SENSOR]


@dataclass
class WalkingPadData:
    """Runtime objects stored on the config entry."""

    coordinator: WalkingPadCoordinator
    treadmill: WalkingPadTreadmill


type WalkingPadConfigEntry = ConfigEntry[WalkingPadData]


async def async_setup_entry(
    hass: HomeAssistant, entry: WalkingPadConfigEntry
) -> bool:
    """Set up WalkingPad from a config entry."""
    address: str = entry.data[CONF_ADDRESS]

    ble_device = bluetooth.async_ble_device_from_address(
        hass, address, connectable=True
    )
    if ble_device is None:
        raise ConfigEntryNotReady(
            f"Could not find WalkingPad {address}. Make sure it is powered on "
            "and in range of Home Assistant or an active Bluetooth proxy."
        )

    treadmill = WalkingPadTreadmill(ble_device)
    try:
        await treadmill.async_ensure_connected()
    except TRANSIENT_ERRORS as err:
        raise ConfigEntryNotReady(
            f"Could not connect to WalkingPad {address}: {err}"
        ) from err

    coordinator = WalkingPadCoordinator(hass, entry, treadmill, address)
    coordinator.async_set_updated_data(treadmill.data)
    entry.runtime_data = WalkingPadData(coordinator=coordinator, treadmill=treadmill)

    @callback
    def _async_on_advertisement(
        service_info: BluetoothServiceInfoBleak, change: BluetoothChange
    ) -> None:
        """Refresh the device handle and reconnect when the pad reappears."""
        treadmill.set_ble_device_and_advertisement_data(
            service_info.device, service_info.advertisement
        )
        if not treadmill.connected:
            entry.async_create_background_task(
                hass,
                treadmill.async_ensure_connected_safe(),
                name=f"{DOMAIN} reconnect {address}",
            )

    entry.async_on_unload(
        bluetooth.async_register_callback(
            hass,
            _async_on_advertisement,
            BluetoothCallbackMatcher(address=address, connectable=True),
            BluetoothScanningMode.ACTIVE,
        )
    )
    entry.async_on_unload(coordinator.async_unload)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: WalkingPadConfigEntry
) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        await entry.runtime_data.treadmill.async_shutdown()
    return unload_ok
