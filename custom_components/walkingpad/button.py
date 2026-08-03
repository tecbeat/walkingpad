"""Button platform for the WalkingPad treadmill.

Mirrors the physical remote: one toggle button that starts the belt at
the currently configured speed slider value, and stops it on the next
press. Waking the pad from STANDBY is handled automatically as part of
the start sequence, so there is no separate power/wake button.
"""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import WalkingPadConfigEntry
from .entity import WalkingPadEntity
from .protocol import Status


async def async_setup_entry(
    hass: HomeAssistant,
    entry: WalkingPadConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the toggle button."""
    async_add_entities([WalkingPadToggleButton(entry.runtime_data.coordinator)])


class WalkingPadToggleButton(WalkingPadEntity, ButtonEntity):
    """Start-when-stopped / stop-when-running toggle.

    Start reads the target speed from the ``number.walkingpad_speed``
    slider (the pad reports the slider's setpoint back to the
    coordinator), so the user configures speed once and then the button
    is a single one-shot control.
    """

    _attr_translation_key = "toggle"
    _attr_icon = "mdi:play-pause"

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.address}_toggle"

    async def async_press(self) -> None:
        treadmill = self.coordinator.treadmill
        # STOPPING is treated as "already on its way down" — a second
        # press during the stop transition does NOT reboot the belt.
        # The user has to wait for the pad to reach STOPPED before it
        # counts as a fresh start.
        if self.data.status in (Status.RUNNING, Status.STARTING, Status.STOPPING):
            if self.data.status is not Status.STOPPING:
                await treadmill.async_stop()
            return
        # Read the current setpoint from the speed number entity. The
        # coordinator stores it under ``target_speed_deci_kmh`` (set by
        # the number entity's async_set_native_value); fall back to the
        # default start speed if the user has not touched the slider.
        from .const import DEFAULT_START_SPEED_DECI_KMH

        deci = getattr(
            self.coordinator, "target_speed_deci_kmh", None
        ) or DEFAULT_START_SPEED_DECI_KMH
        await treadmill.async_start_walking(int(deci))
