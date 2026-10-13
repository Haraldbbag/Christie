"""Power status sensor."""

from __future__ import annotations

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .common import POWER_STATES
from .coordinator import ProjectorConfigEntry, ProjectorCoordinator
from .entity import ProjectorEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ProjectorConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    if entry.runtime_data.driver.has_status:
        async_add_entities([ProjectorPowerStatus(entry.runtime_data)])


class ProjectorPowerStatus(ProjectorEntity, SensorEntity):
    _attr_translation_key = "status"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = [*dict.fromkeys(POWER_STATES.values()), "unknown"]

    def __init__(self, coordinator: ProjectorCoordinator) -> None:
        super().__init__(coordinator, "status")

    @property
    def native_value(self) -> str | None:
        state = self.coordinator.data.state
        if state is None:
            return None
        return POWER_STATES.get(state, "unknown")

    @property
    def extra_state_attributes(self) -> dict:
        d = self.coordinator.data
        return {
            "pwr": d.power_raw,
            "pwr_stat": d.power_status_raw,
            "cooldown_seconds": d.cooldown,
        }
