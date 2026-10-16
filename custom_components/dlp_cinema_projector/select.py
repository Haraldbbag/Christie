"""Power state, channel and test pattern selection."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .common import (
    PWR_COOLING,
    PWR_HIBERNATE,
    PWR_LIGHT_OFF,
    PWR_ON,
    PWR_STANDBY,
    PWR_WARMING,
)
from .common import visible_items
from .const import CONF_VISIBLE_CHANNELS, CONF_VISIBLE_PATTERNS, PATTERN_OFF
from .coordinator import ProjectorConfigEntry, ProjectorCoordinator
from .entity import ProjectorEntity

_CURRENT = {
    PWR_ON: "lamp_on",
    PWR_WARMING: "lamp_on",
    PWR_LIGHT_OFF: "lamp_off",
    PWR_COOLING: "lamp_off",
    PWR_STANDBY: "standby",
    PWR_HIBERNATE: "standby",
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ProjectorConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    c = entry.runtime_data
    entities: list[SelectEntity] = [ProjectorPower(c), ProjectorChannel(c)]
    if c.driver.has_patterns:
        entities.append(ProjectorPattern(c))
    async_add_entities(entities)


class ProjectorPower(ProjectorEntity, SelectEntity):
    """Standby (Christie only) / light source off / light source on."""

    _attr_translation_key = "power"

    def __init__(self, coordinator: ProjectorCoordinator) -> None:
        super().__init__(coordinator, "power_select")
        self._attr_options = list(coordinator.driver.power_options)

    @property
    def current_option(self) -> str | None:
        # The target from PWR? (0/1/3) is what was chosen; PWR+STAT only adds the
        # transition (warming up / cooling down), which the status sensor shows.
        d = self.coordinator.data
        if d.power in (PWR_LIGHT_OFF, PWR_ON, PWR_STANDBY):
            return _CURRENT[d.power]
        return _CURRENT.get(d.state)

    async def async_select_option(self, option: str) -> None:
        await self.coordinator.async_set_power(option)


class ProjectorChannel(ProjectorEntity, SelectEntity):
    _attr_translation_key = "channel"

    def __init__(self, coordinator: ProjectorCoordinator) -> None:
        super().__init__(coordinator, "channel")

    @property
    def options(self) -> list[str]:
        return visible_items(
            self.coordinator.data.channels,
            self.coordinator.config_entry.options.get(CONF_VISIBLE_CHANNELS),
            self.current_option,
        )

    @property
    def current_option(self) -> str | None:
        return self.coordinator.data.channel

    async def async_select_option(self, option: str) -> None:
        await self.coordinator.async_set_channel(option)


class ProjectorPattern(ProjectorEntity, SelectEntity):
    _attr_translation_key = "test_pattern"

    def __init__(self, coordinator: ProjectorCoordinator) -> None:
        super().__init__(coordinator, "test_pattern")

    @property
    def options(self) -> list[str]:
        return [
            PATTERN_OFF,
            *visible_items(
                self.coordinator.data.patterns,
                self.coordinator.config_entry.options.get(CONF_VISIBLE_PATTERNS),
                self.coordinator.data.pattern,
            ),
        ]

    @property
    def current_option(self) -> str | None:
        d = self.coordinator.data
        if not d.pattern_known:
            return None  # e.g. Series 2 in standby does not answer ITP?
        return d.pattern or PATTERN_OFF

    async def async_select_option(self, option: str) -> None:
        await self.coordinator.async_set_pattern(option)
