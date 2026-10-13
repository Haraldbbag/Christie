"""Polling coordinator, independent of the projector manufacturer."""

from __future__ import annotations

import asyncio
from datetime import timedelta
import logging
import time

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .common import (
    PWR_COOLING,
    PWR_ON,
    PWR_WARMING,
    ProjectorData,
    ProjectorError,
    ProjectorInfo,
)
from .const import (
    BURST_INTERVAL,
    BURST_SECONDS,
    CONF_READ_ONLY,
    CONF_SCAN_INTERVAL,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    LIST_REFRESH,
    PATTERN_OFF,
    POWER_BURST_SECONDS,
)
from .driver import Driver

_LOGGER = logging.getLogger(__name__)

type ProjectorConfigEntry = ConfigEntry[ProjectorCoordinator]


class ProjectorCoordinator(DataUpdateCoordinator[ProjectorData]):
    config_entry: ProjectorConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ProjectorConfigEntry,
        driver: Driver,
        info: ProjectorInfo,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN} {entry.title}",
            update_interval=timedelta(
                seconds=entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
            ),
        )
        self.driver = driver
        self.info = info
        self.read_only: bool = entry.options.get(CONF_READ_ONLY, False)
        self._data = ProjectorData()
        self._lists_at: float | None = None
        self._burst_task: asyncio.Task | None = None
        self._was_on = False

    # -- polling ------------------------------------------------------------

    async def _async_update_data(self) -> ProjectorData:
        d = self._data
        try:
            await self.driver.update_power(d)
            is_on = d.state in (PWR_ON, PWR_WARMING)
            if (
                self._lists_at is None
                or time.monotonic() - self._lists_at > LIST_REFRESH
                or (is_on and not self._was_on)
            ):
                self._lists_at = time.monotonic()
                await self.driver.read_lists(d)
            self._was_on = is_on
            await self.driver.update_rest(d)
        except ProjectorError as err:
            raise UpdateFailed(str(err)) from err
        return d

    async def async_refresh_lists(self) -> None:
        try:
            self._lists_at = time.monotonic()
            await self.driver.read_lists(self._data)
        except ProjectorError as err:
            raise HomeAssistantError(f"{self.config_entry.title}: {err}") from err
        self.async_update_listeners()

    # -- commands -----------------------------------------------------------

    def _check_writable(self) -> None:
        if self.read_only:
            raise HomeAssistantError(
                f"{self.config_entry.title} ist auf „Nur lesen“ gestellt (Optionen der Integration)."
            )

    async def _do(self, coro_factory, burst: float) -> None:
        self._check_writable()
        try:
            await coro_factory()
        except ProjectorError as err:
            raise HomeAssistantError(f"{self.config_entry.title}: {err}") from err
        self._start_burst(burst)

    async def async_set_power(self, option: str) -> None:
        await self._do(lambda: self.driver.set_power(option), POWER_BURST_SECONDS)

    async def async_set_shutter(self, closed: bool) -> None:
        await self._do(lambda: self.driver.set_shutter(closed), BURST_SECONDS)

    async def async_set_channel(self, name: str) -> None:
        await self._do(lambda: self.driver.set_channel(name), BURST_SECONDS)

    async def async_set_pattern(self, name: str) -> None:
        value = None if name == PATTERN_OFF else name
        await self._do(lambda: self.driver.set_pattern(value), BURST_SECONDS)

    async def async_send_raw(self, command: str) -> list[str]:
        if not self.driver.is_read_command(command):
            self._check_writable()
        try:
            replies = await self.driver.send_raw(command)
        except ProjectorError as err:
            raise HomeAssistantError(f"{self.config_entry.title}: {err}") from err
        self._start_burst(BURST_SECONDS)
        return replies

    # -- fast polling after a command ------------------------------------------

    def _start_burst(self, seconds: float) -> None:
        if self._burst_task is not None and not self._burst_task.done():
            self._burst_task.cancel()
        self._burst_task = self.config_entry.async_create_background_task(
            self.hass, self._burst(seconds), f"{DOMAIN}_burst"
        )

    async def _burst(self, seconds: float) -> None:
        start = time.monotonic()
        await self.async_refresh()
        while time.monotonic() - start < seconds:
            await asyncio.sleep(BURST_INTERVAL)
            await self.async_refresh()
            # After a power change keep going only while it is still in transition.
            if seconds > BURST_SECONDS and time.monotonic() - start > 10:
                if self.data.state not in (PWR_COOLING, PWR_WARMING):
                    break

    async def async_shutdown(self) -> None:
        if self._burst_task is not None:
            self._burst_task.cancel()
        await super().async_shutdown()
        await self.driver.close()
