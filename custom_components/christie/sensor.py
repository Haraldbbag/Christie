"""Power status sensor."""

from __future__ import annotations

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import POWER_STATES
from .coordinator import ChristieConfigEntry, ChristieCoordinator
from .entity import ChristieEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ChristieConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities([ChristiePowerStatus(entry.runtime_data)])


class ChristiePowerStatus(ChristieEntity, SensorEntity):
    _attr_translation_key = "status"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = [*dict.fromkeys(POWER_STATES.values()), "unknown"]

    def __init__(self, coordinator: ChristieCoordinator) -> None:
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
