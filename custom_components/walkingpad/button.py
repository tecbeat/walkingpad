"""Button platform (start/stop) for the WalkingPad treadmill.

Only Start and Stop live here. Wake/Sleep are exposed via the Power
switch, mode selection via the Mode select. Each button press results in
a single command to the pad — no chained beeps.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import WalkingPadConfigEntry
from .entity import WalkingPadEntity
from .protocol import Status
from .walkingpad import WalkingPadTreadmill


@dataclass(frozen=True, kw_only=True)
class WalkingPadButtonEntityDescription(ButtonEntityDescription):
    """Describes a WalkingPad button."""

    press_fn: Callable[[WalkingPadTreadmill, Status], Awaitable[None]]


BUTTONS: tuple[WalkingPadButtonEntityDescription, ...] = (
    WalkingPadButtonEntityDescription(
        key="start",
        translation_key="start",
        icon="mdi:play",
        press_fn=lambda treadmill, _status: treadmill.async_start(),
    ),
    WalkingPadButtonEntityDescription(
        key="stop",
        translation_key="stop",
        icon="mdi:stop",
        press_fn=lambda treadmill, _status: treadmill.async_stop(),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: WalkingPadConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up WalkingPad buttons."""
    coordinator = entry.runtime_data.coordinator
    async_add_entities(
        WalkingPadButton(coordinator, description) for description in BUTTONS
    )


class WalkingPadButton(WalkingPadEntity, ButtonEntity):
    """A treadmill control button."""

    entity_description: WalkingPadButtonEntityDescription

    def __init__(self, coordinator, description) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{coordinator.address}_{description.key}"

    async def async_press(self) -> None:
        await self.entity_description.press_fn(
            self.coordinator.treadmill, self.data.status
        )
