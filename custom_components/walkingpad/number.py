"""Number platform (target speed) for the WalkingPad treadmill.

The slider stores the user's target speed. It never starts or stops the
belt by itself — that is the Start/Stop button's job.

The slider has a dynamic minimum value that matches what the pad
actually accepts:

- When the belt is stopped (or the pad is asleep / disconnected), the
  minimum is 0.7 km/h. The A1 motor will not spin up below that.
- When the belt is running, the minimum drops to 0.5 km/h. Once the
  belt is in motion the pad can regulate down to a slower pace.

If the user has the slider on 0.5 or 0.6 while the belt is running and
then presses Stop, the setpoint is automatically bumped up to 0.7 so
the next Start press works.
"""

from __future__ import annotations

from homeassistant.components.number import NumberDeviceClass, NumberEntity, NumberMode
from homeassistant.const import UnitOfSpeed
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util.unit_system import US_CUSTOMARY_SYSTEM

from . import WalkingPadConfigEntry
from .const import (
    DEFAULT_START_SPEED_DECI_KMH,
    MAX_SPEED_KMH,
    MIN_SPEED_RUNNING_KMH,
    MIN_SPEED_START_KMH,
    SPEED_STEP_KMH,
)
from .entity import WalkingPadEntity
from .protocol import KMH_PER_MPH, Status

MIN_SPEED_START_DECI_KMH = int(round(MIN_SPEED_START_KMH * 10))
MIN_SPEED_RUNNING_DECI_KMH = int(round(MIN_SPEED_RUNNING_KMH * 10))
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

        self._attr_native_max_value = round(MAX_SPEED_KMH / self._native_to_kmh, 2)
        self._attr_native_step = SPEED_STEP_KMH

        # Seed the coordinator's target speed with the default so a
        # fresh install has a starting value.
        if coordinator.target_speed_deci_kmh is None:
            coordinator.target_speed_deci_kmh = DEFAULT_START_SPEED_DECI_KMH

    @property
    def available(self) -> bool:
        return True

    def _min_deci_kmh(self) -> int:
        """Lower bound in tenths of km/h for the current belt state.

        0.5 km/h while running (belt already moving, pad can regulate
        down that low), 0.7 km/h otherwise (motor cannot spin up below
        that from a stop).
        """
        if self.data.status in (Status.RUNNING, Status.STARTING):
            return MIN_SPEED_RUNNING_DECI_KMH
        return MIN_SPEED_START_DECI_KMH

    @property
    def native_min_value(self) -> float:
        return round(self._min_deci_kmh() / 10.0 / self._native_to_kmh, 2)

    @property
    def native_value(self) -> float:
        deci = self.coordinator.target_speed_deci_kmh
        kmh = deci / 10.0
        return round(kmh / self._native_to_kmh, 2)

    async def async_set_native_value(self, value: float) -> None:
        speed_kmh = value * self._native_to_kmh
        deci_kmh = int(round(speed_kmh * 10))
        # Clamp to the currently valid range. The lower bound depends
        # on whether the belt is running (0.5 km/h) or stopped
        # (0.7 km/h). HA's own bound-check should already have rejected
        # out-of-range calls, but the clamp is defensive.
        deci_kmh = max(self._min_deci_kmh(), min(deci_kmh, MAX_SPEED_DECI_KMH))
        self.coordinator.target_speed_deci_kmh = deci_kmh
        # Reflect the new setpoint immediately so the UI does not flash
        # 0 while waiting for the pad to echo back.
        self.async_write_ha_state()
        # Only push to the pad if the belt is actually running — the
        # slider never starts or stops the belt itself.
        if self.data.status in (Status.RUNNING, Status.STARTING):
            await self.coordinator.treadmill.async_set_speed(deci_kmh)

    @callback
    def _handle_coordinator_update(self) -> None:
        # If the belt just stopped and the setpoint is below the
        # start-minimum (0.7 km/h), bump it up so the next Start press
        # is valid. Without this, the slider would show a value below
        # its own new minimum and the toggle button would fail to
        # start the belt.
        if self.data.status not in (Status.RUNNING, Status.STARTING):
            deci = self.coordinator.target_speed_deci_kmh
            if deci is not None and deci < MIN_SPEED_START_DECI_KMH:
                self.coordinator.target_speed_deci_kmh = MIN_SPEED_START_DECI_KMH
        super()._handle_coordinator_update()
