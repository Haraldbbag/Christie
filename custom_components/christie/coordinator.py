"""Polling coordinator for Christie projectors."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import timedelta
import logging
import time

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from . import protocol as p
from .client import ChristieClient, ChristieCommandError, ChristieError, ChristieTimeout, DeviceInfo
from .const import (
    BURST_INTERVAL,
    BURST_SECONDS,
    CONF_CHANNELS,
    CONF_READ_ONLY,
    CONF_SCAN_INTERVAL,
    DEFAULT_CHANNELS,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    LIST_REFRESH,
    PATTERN_OFF,
    POWER_BURST_SECONDS,
    POWER_COMMANDS,
    POWER_STATES,
    PWR_COOLING,
    PWR_ON,
    PWR_WARMING,
)

_LOGGER = logging.getLogger(__name__)

type ChristieConfigEntry = ConfigEntry[ChristieCoordinator]


@dataclass(slots=True)
class ChristieData:
    power: int | None = None  # PWR? (target state)
    power_status: int | None = None  # PWR+STAT? if the model answers it
    power_raw: str | None = None
    power_status_raw: str | None = None
    cooldown: int | None = None
    shutter: int | None = None  # 0 open, 1 closed
    channel: str | None = None
    pattern: str | None = None  # None = no test pattern
    channels: list[str] = field(default_factory=list)
    patterns: list[str] = field(default_factory=list)
    channels_from_projector: bool = False
    channel_numbers: dict[str, int] = field(default_factory=dict)  # numbered channels
    pattern_known: bool = False

    @property
    def state(self) -> int | None:
        """Best value for the actual power state."""
        if self.power_status is not None and self.power_status in POWER_STATES:
            return self.power_status
        return self.power


class ChristieCoordinator(DataUpdateCoordinator[ChristieData]):
    config_entry: ChristieConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ChristieConfigEntry,
        client: ChristieClient,
        info: DeviceInfo,
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
        self.client = client
        self.info = info
        self.read_only: bool = entry.options.get(CONF_READ_ONLY, False)
        self._data = ChristieData()
        self._lists_at: float | None = None
        self._unsupported: set[str] = set()
        self._burst_task: asyncio.Task | None = None
        self._was_on = False
        self._numeric_channels = False  # model answers CHA? with a number
        self._channel_offset = 0  # Series 2 numbers channels 101..164

    # -- polling ------------------------------------------------------------

    async def _query(self, key: str) -> p.Message | None:
        """Ask one value; None if the model does not support it."""
        if key in self._unsupported:
            return None
        try:
            return await self.client.request(key)
        except ChristieTimeout as err:
            if key == "PWR":
                await self.client.close()  # reconnect on the next poll
                raise
            _LOGGER.info("%s: %s – wird nicht mehr abgefragt", self.config_entry.title, err)
            self._unsupported.add(key)
            return None
        except ChristieCommandError as err:
            _LOGGER.debug("%s: %s", self.config_entry.title, err)
            if "unknown" in str(err).lower() or "invalid" in str(err).lower():
                _LOGGER.info("%s: %s wird nicht unterstützt (%s)", self.config_entry.title, key, err)
                self._unsupported.add(key)
            return None

    async def _async_update_data(self) -> ChristieData:
        d = self._data
        try:
            if (m := await self._query("PWR")) is not None:
                d.power, d.power_raw = m.number, m.data
            if (m := await self._query("PWR+STAT")) is not None:
                d.power_status, d.power_status_raw = m.number, m.data
            if d.state == PWR_COOLING:
                m = await self._query("PWR+COOL")
                d.cooldown = m.number if m is not None else None
            else:
                d.cooldown = None
            is_on = d.state in (PWR_ON, PWR_WARMING)
            if (
                self._lists_at is None
                or time.monotonic() - self._lists_at > LIST_REFRESH
                or (is_on and not self._was_on)
            ):
                await self._read_lists()
            self._was_on = is_on
            if (m := await self._query("SHU")) is not None:
                d.shutter = m.number
            if (m := await self._query("CHA")) is not None:
                d.channel = self._channel_name(m)
            if (m := await self._query("ITP")) is not None:
                d.pattern = _pattern_name(m)
                d.pattern_known = True

        except ChristieError as err:
            raise UpdateFailed(str(err)) from err
        return d

    async def _read_lists(self) -> None:
        d = self._data
        self._lists_at = time.monotonic()
        self._unsupported.clear()  # give skipped queries another chance now and then
        d.channel_numbers = {}
        try:
            channels = await self.client.request_list("CHA")
        except ChristieCommandError as err:
            _LOGGER.debug("%s: no channel list: %s", self.config_entry.title, err)
            channels = []
        d.channels_from_projector = bool(channels)
        if not channels:
            # Series 2: numbered channels, names via (NAM+CALL?) -> (NAM+CALL!"Name" 00001)
            try:
                replies = await self.client.request_all("NAM+CALL")
            except ChristieCommandError as err:
                _LOGGER.debug("%s: no channel names: %s", self.config_entry.title, err)
                replies = []
            for m in replies:
                name = (m.text or "").strip()
                numbers = [int(x) for x in m.params if x.isdigit()]
                if not name or not numbers:
                    continue
                if name in d.channel_numbers:
                    name = f"{name} ({numbers[-1]})"
                d.channel_numbers[name] = numbers[-1]
            channels = list(d.channel_numbers)
        if not channels:
            channels = self._configured_channels()
            d.channel_numbers = {name: i + 1 for i, name in enumerate(channels)}
        d.channels = channels
        try:
            patterns = await self.client.request_list("ITP")
        except ChristieCommandError as err:
            _LOGGER.debug("%s: no test pattern list: %s", self.config_entry.title, err)
            patterns = []
        # "Testpattern Off" (Series 2) is the off entry, offered as PATTERN_OFF instead
        patterns = [x for x in patterns if x.strip().lower() not in _OFF_NAMES]
        if patterns or not d.patterns:
            d.patterns = patterns

    def _channel_name(self, m: p.Message) -> str | None:
        """Name reply as is; a numeric reply (Series 2: 101..164) maps to the channel names."""
        if '"' in m.data or m.number is None:
            return m.text
        self._numeric_channels = True
        number = m.number
        if number > 100:
            self._channel_offset = 100
            number -= 100
        for name, num in self._data.channel_numbers.items():
            if num == number:
                return name
        return str(number)

    def _configured_channels(self) -> list[str]:
        text = self.config_entry.options.get(CONF_CHANNELS)
        if not text:
            return list(DEFAULT_CHANNELS)
        parts = [x.strip() for x in text.replace(",", "\n").splitlines()]
        return [x for x in parts if x]

    async def async_refresh_lists(self) -> None:
        try:
            await self._read_lists()
        except ChristieError as err:
            raise HomeAssistantError(f"Christie: {err}") from err
        self.async_update_listeners()

    # -- commands -----------------------------------------------------------

    def _check_writable(self) -> None:
        if self.read_only:
            raise HomeAssistantError(
                f"{self.config_entry.title} ist auf „Nur lesen“ gestellt (Optionen der Integration)."
            )

    async def _set(self, command: str) -> None:
        self._check_writable()
        try:
            await self.client.set(command)
        except ChristieError as err:
            raise HomeAssistantError(f"Christie: {err}") from err

    async def async_set_power(self, option: str) -> None:
        await self._set(f"PWR {POWER_COMMANDS[option]}")
        self._start_burst(POWER_BURST_SECONDS)

    async def async_set_shutter(self, closed: bool) -> None:
        await self._set(f"SHU {1 if closed else 0}")
        self._start_burst(BURST_SECONDS)

    async def async_set_channel(self, name: str) -> None:
        d = self.data
        if self._numeric_channels and not d.channels_from_projector:
            number = d.channel_numbers.get(name) or int(name)
            await self._set(f"CHA {number + self._channel_offset}")
        else:
            await self._set(f"CHA {p.quote(name)}")
        self._start_burst(BURST_SECONDS)

    async def async_set_pattern(self, name: str) -> None:
        if name == PATTERN_OFF:
            self._check_writable()
            try:
                await self.client.set('ITP ""')
            except ChristieCommandError:
                await self._set("ITP 0")  # older software: 0 = no test pattern
            except ChristieError as err:
                raise HomeAssistantError(f"Christie: {err}") from err
        else:
            await self._set(f"ITP {p.quote(name)}")
        self._start_burst(BURST_SECONDS)

    async def async_send_raw(self, command: str) -> list[str]:
        if not p.is_request(command):
            self._check_writable()
        try:
            replies = await self.client.raw(command)
        except ChristieError as err:
            raise HomeAssistantError(f"Christie: {err}") from err
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
        end = time.monotonic() + seconds
        await self.async_refresh()
        while time.monotonic() < end:
            await asyncio.sleep(BURST_INTERVAL)
            await self.async_refresh()
            d = self.data
            # After a power change keep going only while it is still in transition.
            if seconds > BURST_SECONDS and time.monotonic() > end - seconds + 10:
                if d.state not in (PWR_COOLING, PWR_WARMING):
                    break

    async def async_shutdown(self) -> None:
        if self._burst_task is not None:
            self._burst_task.cancel()
        await super().async_shutdown()
        await self.client.close()


_OFF_NAMES = {"testpattern off", "test pattern off", "off"}


def _pattern_name(m: p.Message) -> str | None:
    """``(ITP!0)``, ``(ITP!000 "Testpattern Off")``, ``(ITP!"")`` = off; else the name."""
    if m.number == 0:
        return None
    if '"' in m.data:
        name = m.text
        return None if not name or name.strip().lower() in _OFF_NAMES else name
    if m.number == 0 or not m.params:
        return None
    return m.params[0]
