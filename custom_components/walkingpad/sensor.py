"""Sensor platform for the WalkingPad treadmill."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    EntityCategory,
    UnitOfLength,
    UnitOfSpeed,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.typing import StateType

from . import WalkingPadConfigEntry
from .entity import WalkingPadEntity
from .protocol import STATUS_STR, TreadmillData

STATE_OPTIONS = [
    "stopped",
    "running",
    "starting",
    "stopping",
    "standby",
    "disconnected",
]

MODE_OPTIONS = ["automat", "manual", "standby"]
MODE_STR = {0: "automat", 1: "manual", 2: "standby"}


@dataclass(frozen=True, kw_only=True)
class WalkingPadSensorEntityDescription(SensorEntityDescription):
    """Describes a WalkingPad sensor."""

    value_fn: Callable[[TreadmillData], StateType]


SENSORS: tuple[WalkingPadSensorEntityDescription, ...] = (
    WalkingPadSensorEntityDescription(
        key="state",
        translation_key="state",
        device_class=SensorDeviceClass.ENUM,
        options=STATE_OPTIONS,
        value_fn=lambda data: STATUS_STR.get(data.status, "stopped"),
    ),
    WalkingPadSensorEntityDescription(
        key="mode",
        translation_key="mode",
        device_class=SensorDeviceClass.ENUM,
        options=MODE_OPTIONS,
        entity_category=EntityCategory.DIAGNOSTIC,
        # Redundant with the Mode select entity; keep as diagnostic for
        # debugging but hide by default.
        entity_registry_enabled_default=False,
        value_fn=lambda data: MODE_STR.get(int(data.mode), "standby"),
    ),
    WalkingPadSensorEntityDescription(
        key="speed_feedback",
        translation_key="speed_feedback",
        device_class=SensorDeviceClass.SPEED,
        native_unit_of_measurement=UnitOfSpeed.KILOMETERS_PER_HOUR,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=lambda data: round(data.speed_feedback, 2),
    ),
    WalkingPadSensorEntityDescription(
        key="distance",
        translation_key="distance",
        device_class=SensorDeviceClass.DISTANCE,
        native_unit_of_measurement=UnitOfLength.KILOMETERS,
        state_class=SensorStateClass.TOTAL_INCREASING,
        suggested_display_precision=2,
        value_fn=lambda data: round(data.distance_km, 3),
    ),
    WalkingPadSensorEntityDescription(
        key="duration",
        translation_key="duration",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda data: data.duration_sec,
    ),
    WalkingPadSensorEntityDescription(
        key="steps",
        translation_key="steps",
        native_unit_of_measurement="steps",
        state_class=SensorStateClass.TOTAL_INCREASING,
        icon="mdi:shoe-print",
        value_fn=lambda data: data.steps,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: WalkingPadConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up WalkingPad sensors."""
    coordinator = entry.runtime_data.coordinator
    async_add_entities(
        WalkingPadSensor(coordinator, description) for description in SENSORS
    )


class WalkingPadSensor(WalkingPadEntity, SensorEntity):
    """A WalkingPad telemetry sensor."""

    entity_description: WalkingPadSensorEntityDescription

    def __init__(self, coordinator, description) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{coordinator.address}_{description.key}"

    @property
    def available(self) -> bool:
        # The State and Mode sensors are the whole point of the "pad is
        # off but not broken" story — they must stay available whenever
        # the coordinator has any data at all, even when the pad is in
        # STANDBY or disconnected (in which case they render as
        # "standby" / "disconnected" values, not "unavailable").
        if self.entity_description.key in ("state", "mode"):
            return self.coordinator.last_update_success
        return super().available

    @property
    def native_value(self) -> StateType:
        return self.entity_description.value_fn(self.data)
