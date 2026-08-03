"""Select platform (walking mode) for the WalkingPad treadmill.

The pad supports three raw modes: STANDBY, MANUAL, and AUTOMAT. STANDBY is
exposed as the Power switch (`switch.walkingpad_power`); the select entity
therefore only offers the two walking modes:

- ``manual``: user controls speed via the slider or Start button.
- ``automat``: pad picks speed based on foot position on the belt.

The selected mode is persisted on the config entry so it survives Home
Assistant restarts, and it is the mode the pad is woken into when the Power
switch is turned on.
"""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import WalkingPadConfigEntry
from .const import CONF_PREFERRED_MODE
from .entity import WalkingPadEntity
from .protocol import Mode

MODE_MANUAL = "manual"
MODE_AUTOMAT = "automat"

OPTION_TO_MODE = {
    MODE_MANUAL: Mode.MANUAL,
    MODE_AUTOMAT: Mode.AUTOMAT,
}
MODE_TO_OPTION = {value: key for key, value in OPTION_TO_MODE.items()}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: WalkingPadConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the walking-mode select entity."""
    async_add_entities([WalkingPadModeSelect(entry.runtime_data.coordinator, entry)])


class WalkingPadModeSelect(WalkingPadEntity, SelectEntity):
    """Dropdown that mirrors and sets the pad's walking mode."""

    _attr_translation_key = "mode"
    _attr_options = [MODE_MANUAL, MODE_AUTOMAT]

    def __init__(self, coordinator, entry: WalkingPadConfigEntry) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = f"{coordinator.address}_mode_select"

    @property
    def available(self) -> bool:
        # Always available: the user must be able to preselect the mode
        # even while the pad is asleep or unreachable. The choice is
        # persisted on the config entry and applied on the next wake.
        return True

    @property
    def current_option(self) -> str | None:
        preferred = self.coordinator.treadmill.preferred_mode
        return MODE_TO_OPTION.get(preferred)

    async def async_select_option(self, option: str) -> None:
        mode = OPTION_TO_MODE[option]
        # Persist first so a mid-command HA restart still remembers the
        # user's choice.
        self.hass.config_entries.async_update_entry(
            self._entry,
            options={**self._entry.options, CONF_PREFERRED_MODE: int(mode)},
        )
        self.coordinator.treadmill.set_preferred_mode(mode)
        # Only push switch_mode to the pad if it is currently awake and
        # reachable. In STANDBY or when disconnected the choice is
        # stored silently and applied on the next wake — no unwanted
        # beep, no error when the pad is not reachable.
        if (
            self.coordinator.treadmill.connected
            and self.data.mode is not Mode.STANDBY
        ):
            await self.coordinator.treadmill.async_switch_mode(mode)
        self.async_write_ha_state()

    @callback
    def _handle_coordinator_update(self) -> None:
        # If the pad reports a mode we didn't ask for (e.g. user pressed a
        # button on the pad itself), reflect it as the preferred mode so
        # the dropdown stays in sync — but only for walking modes.
        current = self.data.mode
        if current in (Mode.MANUAL, Mode.AUTOMAT):
            self.coordinator.treadmill.set_preferred_mode(current)
        super()._handle_coordinator_update()
