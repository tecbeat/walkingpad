"""Config flow for the WalkingPad treadmill integration."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.components.bluetooth import (
    BluetoothServiceInfoBleak,
    async_discovered_service_info,
)
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_ADDRESS

from .const import DEFAULT_NAME, DEVICE_NAME_PREFIX, DOMAIN, SERVICE_PAD_UUID


def _is_supported(discovery_info: BluetoothServiceInfoBleak) -> bool:
    """Return True if the advertisement looks like a supported WalkingPad."""
    if SERVICE_PAD_UUID in discovery_info.service_uuids:
        return True
    name = discovery_info.name or ""
    return name.startswith(DEVICE_NAME_PREFIX)


class WalkingPadConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for WalkingPad."""

    VERSION = 1

    def __init__(self) -> None:
        self._discovery_info: BluetoothServiceInfoBleak | None = None
        self._discovered_devices: dict[str, BluetoothServiceInfoBleak] = {}

    async def async_step_bluetooth(
        self, discovery_info: BluetoothServiceInfoBleak
    ) -> ConfigFlowResult:
        """Handle a WalkingPad discovered over Bluetooth."""
        await self.async_set_unique_id(discovery_info.address)
        self._abort_if_unique_id_configured()
        self._discovery_info = discovery_info
        self.context["title_placeholders"] = {
            "name": discovery_info.name or DEFAULT_NAME
        }
        return await self.async_step_bluetooth_confirm()

    async def async_step_bluetooth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        assert self._discovery_info is not None
        if user_input is not None:
            return self._async_create_entry(self._discovery_info)
        self._set_confirm_only()
        return self.async_show_form(
            step_id="bluetooth_confirm",
            description_placeholders={
                "name": self._discovery_info.name or DEFAULT_NAME
            },
        )

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Pick a WalkingPad from the list of discovered devices."""
        if user_input is not None:
            address = user_input[CONF_ADDRESS]
            await self.async_set_unique_id(address, raise_on_progress=False)
            self._abort_if_unique_id_configured()
            return self._async_create_entry(self._discovered_devices[address])

        current_addresses = self._async_current_ids()
        for discovery_info in async_discovered_service_info(
            self.hass, connectable=True
        ):
            address = discovery_info.address
            if address in current_addresses or address in self._discovered_devices:
                continue
            if _is_supported(discovery_info):
                self._discovered_devices[address] = discovery_info

        if not self._discovered_devices:
            return self.async_abort(reason="no_devices_found")

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_ADDRESS): vol.In(
                        {
                            address: f"{info.name or DEFAULT_NAME} ({address})"
                            for address, info in self._discovered_devices.items()
                        }
                    )
                }
            ),
        )

    def _async_create_entry(
        self, discovery_info: BluetoothServiceInfoBleak
    ) -> ConfigFlowResult:
        return self.async_create_entry(
            title=discovery_info.name or DEFAULT_NAME,
            data={CONF_ADDRESS: discovery_info.address},
        )
