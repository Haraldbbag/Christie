"""Power state, channel and test pattern selection."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import (
    PATTERN_OFF,
    POWER_COMMANDS,
    PWR_COOLING,
    PWR_HIBERNATE,
    PWR_LIGHT_OFF,
    PWR_ON,
    PWR_STANDBY,
    PWR_WARMING,
)
from .coordinator import ChristieConfigEntry, ChristieCoordinator
from .entity import ChristieEntity

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
    entry: ChristieConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    c = entry.runtime_data
    async_add_entities([ChristiePower(c), ChristieChannel(c), ChristiePattern(c)])


class ChristiePower(ChristieEntity, SelectEntity):
    """Standby / light source off / light source on."""

    _attr_translation_key = "power"
    _attr_options = list(POWER_COMMANDS)

    def __init__(self, coordinator: ChristieCoordinator) -> None:
        super().__init__(coordinator, "power_select")

    @property
    def current_option(self) -> str | None:
        return _CURRENT.get(self.coordinator.data.state)

    async def async_select_option(self, option: str) -> None:
        await self.coordinator.async_set_power(option)


class ChristieChannel(ChristieEntity, SelectEntity):
    _attr_translation_key = "channel"

    def __init__(self, coordinator: ChristieCoordinator) -> None:
        super().__init__(coordinator, "channel")

    @property
    def options(self) -> list[str]:
        options = list(self.coordinator.data.channels)
        current = self.current_option
        if current and current not in options:
            options.append(current)
        return options

    @property
    def current_option(self) -> str | None:
        return self.coordinator.data.channel

    async def async_select_option(self, option: str) -> None:
        await self.coordinator.async_set_channel(option)


class ChristiePattern(ChristieEntity, SelectEntity):
    _attr_translation_key = "test_pattern"

    def __init__(self, coordinator: ChristieCoordinator) -> None:
        super().__init__(coordinator, "test_pattern")

    @property
    def options(self) -> list[str]:
        options = [PATTERN_OFF, *self.coordinator.data.patterns]
        current = self.coordinator.data.pattern
        if current and current not in options:
            options.append(current)
        return options

    @property
    def current_option(self) -> str | None:
        d = self.coordinator.data
        if not d.pattern_known:
            return None  # e.g. Series 2 in standby does not answer ITP?
        return d.pattern or PATTERN_OFF

    async def async_select_option(self, option: str) -> None:
        await self.coordinator.async_set_pattern(option)
