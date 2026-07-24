"""Button platform (start/stop/mode) for the WalkingPad treadmill."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import WalkingPadConfigEntry
from .entity import WalkingPadEntity
from .protocol import Mode, Status
from .walkingpad import WalkingPadTreadmill


@dataclass(frozen=True, kw_only=True)
class WalkingPadButtonEntityDescription(ButtonEntityDescription):
    """Describes a WalkingPad button."""

    press_fn: Callable[[WalkingPadTreadmill, Status], Awaitable[None]]


async def _async_toggle_start_stop(
    treadmill: WalkingPadTreadmill, status: Status
) -> None:
    """Stop when running/starting, otherwise start."""
    if status in (Status.RUNNING, Status.STARTING):
        await treadmill.async_stop()
    else:
        await treadmill.async_start()


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
    WalkingPadButtonEntityDescription(
        key="toggle",
        translation_key="toggle",
        icon="mdi:play-pause",
        press_fn=_async_toggle_start_stop,
    ),
    WalkingPadButtonEntityDescription(
        key="mode_manual",
        translation_key="mode_manual",
        icon="mdi:human-handsup",
        entity_registry_enabled_default=False,
        press_fn=lambda treadmill, _status: treadmill.async_switch_mode(Mode.MANUAL),
    ),
    WalkingPadButtonEntityDescription(
        key="mode_standby",
        translation_key="mode_standby",
        icon="mdi:power-standby",
        entity_registry_enabled_default=False,
        press_fn=lambda treadmill, _status: treadmill.async_switch_mode(Mode.STANDBY),
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
