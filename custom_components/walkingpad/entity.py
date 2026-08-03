"""Base entity for the WalkingPad treadmill."""

from __future__ import annotations

from homeassistant.helpers.device_registry import CONNECTION_BLUETOOTH, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DEFAULT_NAME, DOMAIN, MANUFACTURER, MODEL
from .coordinator import WalkingPadCoordinator
from .protocol import Mode, TreadmillData


class WalkingPadEntity(CoordinatorEntity[WalkingPadCoordinator]):
    """Common base wiring device info and availability.

    Default availability is "pad is awake": BLE connected AND not in
    STANDBY. That way, walking-related controls (speed slider, start/stop
    buttons, telemetry sensors) go ``unavailable`` when the pad is off or
    unreachable — which HA renders as a greyed-out control, not an error.
    Sub-classes that must stay available in more states (Power switch,
    Mode select, State sensor) override :attr:`available` themselves.
    """

    _attr_has_entity_name = True

    def __init__(self, coordinator: WalkingPadCoordinator) -> None:
        super().__init__(coordinator)
        self._address = coordinator.address

    @property
    def data(self) -> TreadmillData:
        return self.coordinator.data

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            connections={(CONNECTION_BLUETOOTH, self._address)},
            identifiers={(DOMAIN, self._address)},
            name=self.coordinator.entry.title or DEFAULT_NAME,
            manufacturer=MANUFACTURER,
            model=MODEL,
        )

    @property
    def available(self) -> bool:
        return (
            super().available
            and self.coordinator.treadmill.connected
            and self.data.mode is not Mode.STANDBY
        )
