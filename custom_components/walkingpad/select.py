"""Select platform (walking mode) for the WalkingPad treadmill.

The pad supports three raw modes: STANDBY, MANUAL, and AUTOMAT. STANDBY
is the pad-off state, which the integration reaches transparently — it
is not selectable by the user. The select therefore only offers the two
walking modes:

- ``manual``: user controls speed via the slider or Start button.
- ``automat``: pad picks speed based on foot position on the belt.

The selection is persisted on the config entry so it survives Home
Assistant restarts, and it is the mode the pad is woken into on the
next Start/Stop press.
"""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.core import HomeAssistant
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
    """Dropdown that mirrors and sets the preferred walking mode."""

    _attr_translation_key = "mode"
    _attr_options = [MODE_MANUAL, MODE_AUTOMAT]

    def __init__(self, coordinator, entry: WalkingPadConfigEntry) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = f"{coordinator.address}_mode_select"

    @property
    def available(self) -> bool:
        # Always available: the user must be able to preselect the mode
        # even while the pad is asleep or unreachable.
        return True

    @property
    def current_option(self) -> str:
        # preferred_mode is guaranteed to be MANUAL or AUTOMAT
        # (set_preferred_mode is only called with those two, and the
        # config-entry loader in __init__.py validates the stored value).
        # STANDBY would be a bug — fall back to MANUAL so the dropdown
        # always has a valid option and the user never sees an empty
        # value.
        preferred = self.coordinator.treadmill.preferred_mode
        return MODE_TO_OPTION.get(preferred, MODE_MANUAL)

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
