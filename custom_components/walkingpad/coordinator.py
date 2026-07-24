"""Push-based coordinator for the WalkingPad treadmill."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import DOMAIN
from .protocol import TreadmillData
from .walkingpad import WalkingPadTreadmill

_LOGGER = logging.getLogger(__name__)


class WalkingPadCoordinator(DataUpdateCoordinator[TreadmillData]):
    """Bridges the treadmill's push notifications to HA entities.

    The pad streams a status frame roughly every 750 ms while connected, so
    there is no polling: every notification and every connect/disconnect pushes
    fresh data to the entities.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        treadmill: WalkingPadTreadmill,
        address: str,
    ) -> None:
        super().__init__(hass, _LOGGER, name=f"{DOMAIN}_{address}")
        self.entry = entry
        self.treadmill = treadmill
        self.address = address
        self._unregister = treadmill.register_callback(self._handle_update)

    @callback
    def _handle_update(self, data: TreadmillData) -> None:
        self.async_set_updated_data(data)

    @callback
    def async_unload(self) -> None:
        self._unregister()
