"""Button platform for the WalkingPad treadmill.

One toggle button that mirrors the physical remote: press to start the
belt at the current slider speed, press again to stop. Waking the pad
from STANDBY is handled transparently as part of the start sequence.
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
    """Start-when-stopped / stop-when-running toggle."""

    _attr_translation_key = "toggle"
    _attr_icon = "mdi:play-pause"

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.address}_toggle"

    async def async_press(self) -> None:
        treadmill = self.coordinator.treadmill
        status = self.data.status
        if status in (Status.RUNNING, Status.STARTING):
            await treadmill.async_stop()
            return
        # STOPPING is the ~1 s transition between "user pressed stop"
        # and "pad reports STOPPED". A second press during that window
        # would otherwise start the belt again — ignore it and let the
        # pad finish stopping first.
        if status is Status.STOPPING:
            return
        # The coordinator's target speed is guaranteed to be set by the
        # number entity's __init__ (seeded with DEFAULT_START_SPEED_DECI_KMH
        # if the user has not moved the slider yet).
        await treadmill.async_start_walking(self.coordinator.target_speed_deci_kmh)
