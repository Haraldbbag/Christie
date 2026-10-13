"""Shutter (douser) switch: on = closed."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import ChristieConfigEntry, ChristieCoordinator
from .entity import ChristieEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ChristieConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities([ChristieShutter(entry.runtime_data)])


class ChristieShutter(ChristieEntity, SwitchEntity):
    _attr_translation_key = "shutter_closed"

    def __init__(self, coordinator: ChristieCoordinator) -> None:
        super().__init__(coordinator, "shutter")

    @property
    def is_on(self) -> bool | None:
        shutter = self.coordinator.data.shutter
        return None if shutter is None else shutter == 1

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.async_set_shutter(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.async_set_shutter(False)
