"""Number platform (speed control) for the WalkingPad treadmill."""

from __future__ import annotations

from homeassistant.components.number import NumberDeviceClass, NumberEntity, NumberMode
from homeassistant.const import UnitOfSpeed
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util.unit_system import US_CUSTOMARY_SYSTEM

from . import WalkingPadConfigEntry
from .const import MAX_SPEED_KMH, SPEED_STEP_KMH, STOP_THRESHOLD_KMH
from .entity import WalkingPadEntity
from .protocol import KMH_PER_MPH, Status

STOP_THRESHOLD_DECI_KMH = int(round(STOP_THRESHOLD_KMH * 10))
MAX_SPEED_DECI_KMH = int(round(MAX_SPEED_KMH * 10))


async def async_setup_entry(
    hass: HomeAssistant,
    entry: WalkingPadConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the speed number entity."""
    async_add_entities([WalkingPadSpeedNumber(entry.runtime_data.coordinator)])


class WalkingPadSpeedNumber(WalkingPadEntity, NumberEntity):
    """Target speed slider. Setting a non-zero value (re)starts the belt; 0 stops it.

    The slider is *optimistic*: it holds the value you set instead of mirroring
    the treadmill's live target, so it doesn't creep during acceleration. The
    live belt speed is available on the separate Speed sensor.

    Number entities don't auto-convert the speed device class, so the slider's
    unit follows the user's Home Assistant unit system. The wire protocol is
    always km/h (in tenths), so input is converted back before sending.
    """

    _attr_translation_key = "speed"
    _attr_device_class = NumberDeviceClass.SPEED
    _attr_mode = NumberMode.SLIDER
    _attr_assumed_state = True

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.address}_speed"
        self._setpoint: float | None = None

        if coordinator.hass.config.units is US_CUSTOMARY_SYSTEM:
            self._native_to_kmh = KMH_PER_MPH
            self._attr_native_unit_of_measurement = UnitOfSpeed.MILES_PER_HOUR
        else:
            self._native_to_kmh = 1.0
            self._attr_native_unit_of_measurement = UnitOfSpeed.KILOMETERS_PER_HOUR

        self._attr_native_min_value = 0.0
        self._attr_native_max_value = round(MAX_SPEED_KMH / self._native_to_kmh, 1)
        self._attr_native_step = SPEED_STEP_KMH

    @callback
    def _handle_coordinator_update(self) -> None:
        if self.data.status in (Status.STOPPED, Status.DISCONNECTED):
            self._setpoint = None
        super()._handle_coordinator_update()

    @property
    def native_value(self) -> float:
        if self._setpoint is not None:
            return self._setpoint
        return round(self.data.speed_feedback / self._native_to_kmh, 2)

    async def async_set_native_value(self, value: float) -> None:
        speed_kmh = value * self._native_to_kmh
        deci_kmh = int(round(speed_kmh * 10))
        deci_kmh = max(0, min(deci_kmh, MAX_SPEED_DECI_KMH))
        if deci_kmh <= STOP_THRESHOLD_DECI_KMH:
            self._setpoint = 0.0
            await self.coordinator.treadmill.async_stop()
            self.async_write_ha_state()
            return
        self._setpoint = round(value, 2)
        await self.coordinator.treadmill.async_set_speed(deci_kmh)
        self.async_write_ha_state()
