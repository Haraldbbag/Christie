"""Re-read channel and test pattern lists."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import ProjectorConfigEntry, ProjectorCoordinator
from .entity import ProjectorEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ProjectorConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities([ProjectorRefreshLists(entry.runtime_data)])


class ProjectorRefreshLists(ProjectorEntity, ButtonEntity):
    _attr_translation_key = "refresh_lists"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: ProjectorCoordinator) -> None:
        super().__init__(coordinator, "refresh_lists")

    async def async_press(self) -> None:
        await self.coordinator.async_refresh_lists()
