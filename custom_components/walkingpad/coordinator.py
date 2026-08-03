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

    The A1 does not stream status frames on its own. WalkingPadTreadmill runs
    a ~1 s ask_stats poll loop while connected and pushes each parsed frame
    here via the registered callback.
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
        # Target speed in tenths of km/h, set by the number entity's slider
        # and read by the toggle button when the user starts a walk. This
        # is the "what speed should the belt aim for" value; the pad's
        # own current speed is exposed separately via the speed sensor.
        self.target_speed_deci_kmh: int | None = None
        self._unregister = treadmill.register_callback(self._handle_update)

    @callback
    def _handle_update(self, data: TreadmillData) -> None:
        self.async_set_updated_data(data)

    @callback
    def async_unload(self) -> None:
        self._unregister()
