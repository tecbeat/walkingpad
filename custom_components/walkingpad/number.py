"""Number platform (target speed) for the WalkingPad treadmill.

The slider stores the user's target speed. It does not, by itself, drive
the belt — the toggle button reads this value when the user starts a
walk. That mirrors the physical remote: pick a speed, then press start.

Two live scenarios where the slider DOES send commands:

- Belt is running and the user moves the slider → send ``set_speed``
  immediately (one BLE write, one beep). This is the "adjust while
  walking" case.
- User drags to 0 while the belt is running → send stop.

If the belt is stopped or the pad is asleep, moving the slider is a
pure UI action — it only records the setpoint. The toggle button will
use it when the user starts.
"""

from __future__ import annotations

from homeassistant.components.number import NumberDeviceClass, NumberEntity, NumberMode
from homeassistant.const import UnitOfSpeed
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util.unit_system import US_CUSTOMARY_SYSTEM

from . import WalkingPadConfigEntry
from .const import DEFAULT_START_SPEED_DECI_KMH, MAX_SPEED_KMH, SPEED_STEP_KMH, STOP_THRESHOLD_KMH
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
    """Target-speed slider.

    Always available so the user can pre-configure the target speed
    even while the pad is asleep or unreachable. The pad's actual live
    speed is available on the separate speed sensor.

    While the belt is running, moving the slider immediately sends a
    ``set_speed`` command (one BLE write). Otherwise the slider only
    updates the coordinator's target speed, which the toggle button
    reads when the user starts a walk.
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

        self._attr_native_min_value = 0.0
        self._attr_native_max_value = round(MAX_SPEED_KMH / self._native_to_kmh, 1)
        self._attr_native_step = SPEED_STEP_KMH

        # Seed the coordinator's target speed with a sensible default so
        # a fresh install has a value to start walking at.
        if coordinator.target_speed_deci_kmh is None:
            coordinator.target_speed_deci_kmh = DEFAULT_START_SPEED_DECI_KMH

    @property
    def available(self) -> bool:
        # Always available: the slider is a UI setpoint, useful even
        # while the pad is off. Never show as unavailable.
        return True

    @property
    def native_value(self) -> float:
        deci = self.coordinator.target_speed_deci_kmh
        if deci is None:
            deci = DEFAULT_START_SPEED_DECI_KMH
        kmh = deci / 10.0
        return round(kmh / self._native_to_kmh, 2)

    async def async_set_native_value(self, value: float) -> None:
        speed_kmh = value * self._native_to_kmh
        deci_kmh = int(round(speed_kmh * 10))
        deci_kmh = max(0, min(deci_kmh, MAX_SPEED_DECI_KMH))
        self.coordinator.target_speed_deci_kmh = deci_kmh
        # Reflect the new setpoint immediately so the UI does not flash
        # 0 while waiting for the pad to echo back.
        self.async_write_ha_state()
        # If the belt is running, apply the new target immediately (one
        # BLE write, one beep). Otherwise the setpoint is stored for the
        # next toggle press.
        if self.data.status in (Status.RUNNING, Status.STARTING):
            if deci_kmh <= STOP_THRESHOLD_DECI_KMH:
                await self.coordinator.treadmill.async_stop()
            else:
                await self.coordinator.treadmill.async_set_speed(deci_kmh)

    @callback
    def _handle_coordinator_update(self) -> None:
        # Setpoint is user-controlled, not pad-controlled — do not
        # overwrite it from status frames. Just refresh the entity state
        # so any target_speed_deci_kmh change (e.g. from another client)
        # is reflected.
        super()._handle_coordinator_update()
