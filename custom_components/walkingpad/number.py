"""Number platform (target speed) for the WalkingPad treadmill.

The slider stores the user's target speed. It never starts or stops the
belt by itself — that is the Start/Stop button's job. The slider only
offers real walking speeds (0.5..6.0 km/h); values below 0.5 are
rejected by the pad's motor controller.

Two scenarios:

- Belt is stopped / pad is asleep: moving the slider is a pure UI
  action, it only records the target speed. The next Start/Stop press
  uses this value.
- Belt is running: moving the slider sends one ``set_speed`` command
  to the pad (one BLE write, one beep).
"""

from __future__ import annotations

from homeassistant.components.number import NumberDeviceClass, NumberEntity, NumberMode
from homeassistant.const import UnitOfSpeed
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util.unit_system import US_CUSTOMARY_SYSTEM

from . import WalkingPadConfigEntry
from .const import (
    DEFAULT_START_SPEED_DECI_KMH,
    MAX_SPEED_KMH,
    MIN_SPEED_KMH,
    SPEED_STEP_KMH,
)
from .entity import WalkingPadEntity
from .protocol import KMH_PER_MPH, Status

MIN_SPEED_DECI_KMH = int(round(MIN_SPEED_KMH * 10))
MAX_SPEED_DECI_KMH = int(round(MAX_SPEED_KMH * 10))


async def async_setup_entry(
    hass: HomeAssistant,
    entry: WalkingPadConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the speed number entity."""
    async_add_entities([WalkingPadSpeedNumber(entry.runtime_data.coordinator)])


class WalkingPadSpeedNumber(WalkingPadEntity, NumberEntity):
    """Target-speed slider.

    Always available so the user can pre-configure the target speed
    even while the pad is asleep or unreachable. The pad's actual live
    speed is exposed separately via ``sensor.walkingpad_speed``.
    """

    _attr_translation_key = "speed"
    _attr_device_class = NumberDeviceClass.SPEED
    _attr_mode = NumberMode.SLIDER
    _attr_assumed_state = True

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.address}_speed"

        if coordinator.hass.config.units is US_CUSTOMARY_SYSTEM:
            self._native_to_kmh = KMH_PER_MPH
            self._attr_native_unit_of_measurement = UnitOfSpeed.MILES_PER_HOUR
        else:
            self._native_to_kmh = 1.0
            self._attr_native_unit_of_measurement = UnitOfSpeed.KILOMETERS_PER_HOUR

        self._attr_native_min_value = round(MIN_SPEED_KMH / self._native_to_kmh, 2)
        self._attr_native_max_value = round(MAX_SPEED_KMH / self._native_to_kmh, 2)
        self._attr_native_step = SPEED_STEP_KMH

        # Seed the coordinator's target speed with the default so a
        # fresh install has a starting value.
        if coordinator.target_speed_deci_kmh is None:
            coordinator.target_speed_deci_kmh = DEFAULT_START_SPEED_DECI_KMH

    @property
    def available(self) -> bool:
        return True

    @property
    def native_value(self) -> float:
        deci = self.coordinator.target_speed_deci_kmh
        kmh = deci / 10.0
        return round(kmh / self._native_to_kmh, 2)

    async def async_set_native_value(self, value: float) -> None:
        speed_kmh = value * self._native_to_kmh
        deci_kmh = int(round(speed_kmh * 10))
        # Clamp to the walking range — 0.5..6.0 km/h. Values below the
        # minimum snap up to the minimum, which is what the slider
        # bounds should already enforce; the clamp is defensive.
        deci_kmh = max(MIN_SPEED_DECI_KMH, min(deci_kmh, MAX_SPEED_DECI_KMH))
        self.coordinator.target_speed_deci_kmh = deci_kmh
        # Reflect the new setpoint immediately so the UI does not flash
        # 0 while waiting for the pad to echo back.
        self.async_write_ha_state()
        # Only push to the pad if the belt is actually running — the
        # slider never starts or stops the belt itself.
        if self.data.status in (Status.RUNNING, Status.STARTING):
            await self.coordinator.treadmill.async_set_speed(deci_kmh)
