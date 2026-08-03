"""Base entity for the WalkingPad treadmill."""

from __future__ import annotations

from homeassistant.helpers.device_registry import CONNECTION_BLUETOOTH, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DEFAULT_NAME, DOMAIN, MANUFACTURER, MODEL
from .coordinator import WalkingPadCoordinator
from .protocol import TreadmillData


class WalkingPadEntity(CoordinatorEntity[WalkingPadCoordinator]):
    """Common base wiring device info and availability.

    Entities are considered available as long as the coordinator has
    received data at least once. STANDBY and DISCONNECTED are normal
    states, not errors: the pad-off case must not paint the whole
    device red in Home Assistant. Sub-classes that need stricter
    availability override :attr:`available` themselves.
    """

    _attr_has_entity_name = True

    @property
    def data(self) -> TreadmillData:
        return self.coordinator.data

    @property
    def device_info(self) -> DeviceInfo:
        address = self.coordinator.address
        return DeviceInfo(
            connections={(CONNECTION_BLUETOOTH, address)},
            identifiers={(DOMAIN, address)},
            name=self.coordinator.entry.title or DEFAULT_NAME,
            manufacturer=MANUFACTURER,
            model=MODEL,
        )

    @property
    def available(self) -> bool:
        # STANDBY and DISCONNECTED are normal states, not errors — they
        # are represented via the sensor values themselves, not via the
        # availability flag. Entities stay available as long as the
        # coordinator has received data at least once (which happens
        # synchronously in async_setup_entry via async_set_updated_data).
        return self.coordinator.last_update_success
