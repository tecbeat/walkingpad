"""Diagnostics support for the WalkingPad treadmill integration.

Dumps enough state to debug a stuck connection, wrong mode, or a
misbehaving toggle sequence without exposing any personal data. The
Bluetooth MAC address is public information (broadcasted in every
advertisement) so it is not redacted.
"""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant

from . import WalkingPadConfigEntry


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: WalkingPadConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    runtime = entry.runtime_data
    coordinator = runtime.coordinator
    treadmill = runtime.treadmill
    data = coordinator.data

    return {
        "entry": {
            "title": entry.title,
            "data": dict(entry.data),
            "options": dict(entry.options),
        },
        "connection": {
            "connected": treadmill.connected,
            "address": treadmill.address,
            "name": treadmill.name,
        },
        "coordinator": {
            "target_speed_deci_kmh": coordinator.target_speed_deci_kmh,
            "last_update_success": coordinator.last_update_success,
        },
        "treadmill": {
            "preferred_mode": treadmill.preferred_mode.name,
        },
        "data": {
            "status": data.status.name,
            "mode": data.mode.name,
            "speed_feedback_kmh": data.speed_feedback,
            "distance_km": data.distance_km,
            "steps": data.steps,
            "duration_sec": data.duration_sec,
            "last_button": data.last_button,
        },
    }
