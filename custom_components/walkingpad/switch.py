"""Switch platform (Power) for the WalkingPad treadmill.

The Power switch is the main on/off control users interact with: turning it
on wakes the pad from STANDBY into the currently selected walking mode
(MANUAL or AUTOMAT), turning it off puts the pad back into STANDBY.

It is intentionally the ONLY entity that stays available while the pad is
unreachable — that way, an off pad appears as "power switch: off" instead of
"integration is broken", and every other control becomes available only
once the pad is actually reachable.
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchDeviceClass, SwitchEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import WalkingPadConfigEntry
from .entity import WalkingPadEntity
from .protocol import Mode, Status


async def async_setup_entry(
    hass: HomeAssistant,
    entry: WalkingPadConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the power switch."""
    async_add_entities([WalkingPadPowerSwitch(entry.runtime_data.coordinator)])


class WalkingPadPowerSwitch(WalkingPadEntity, SwitchEntity):
    """On = pad awake in preferred walking mode; Off = pad in STANDBY."""

    _attr_translation_key = "power"
    _attr_device_class = SwitchDeviceClass.SWITCH
    _attr_icon = "mdi:power"

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.address}_power"

    @property
    def available(self) -> bool:
        # The power switch stays available even when the pad is disconnected
        # (unplugged, out of range) — the whole point of the switch is to
        # make an "off" pad a normal state, not an error state. Turning it
        # on in that case is a no-op that will succeed as soon as the pad
        # comes back into range.
        return True

    @property
    def is_on(self) -> bool | None:
        if self.data.status is Status.DISCONNECTED:
            # Pad unreachable — treat as off. A reconnect will refresh
            # this to the actual mode.
            return False
        return self.data.mode is not Mode.STANDBY

    async def async_turn_on(self, **_kwargs: Any) -> None:
        await self.coordinator.treadmill.async_wake()

    async def async_turn_off(self, **_kwargs: Any) -> None:
        await self.coordinator.treadmill.async_sleep()
