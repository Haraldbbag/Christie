"""Christie driver: Series 2 (TPC) and CineLife/CineLife+ text protocol."""

from __future__ import annotations

import logging

from . import christie_protocol as p
from .christie_client import ChristieClient
from .common import (
    PWR_COOLING,
    ProjectorCommandError,
    ProjectorData,
    ProjectorInfo,
    ProjectorTimeout,
)
from .driver import Driver

_LOGGER = logging.getLogger(__name__)

_OFF_NAMES = {"testpattern off", "test pattern off", "off"}

# Channel names used when the projector cannot list its channels (CineLife defaults)
DEFAULT_CHANNELS = ["Media Block Flat", "Media Block Scope", "HDMI A", "HDMI B", "HDMI 3D LR"]


class ChristieDriver(Driver):
    manufacturer = "Christie"
    power_options = ["standby", "lamp_off", "lamp_on"]
    has_status = True
    has_patterns = True

    def __init__(
        self,
        host: str,
        port: int,
        username: str | None = None,
        password: str | None = None,
        channel_names: list[str] | None = None,
    ) -> None:
        self.client = ChristieClient(host, port, username, password)
        self.host = host
        self._configured_channels = channel_names or []
        self._unsupported: set[str] = set()
        self._numeric_channels = False  # model answers CHA? with a number
        self._channel_offset = 0  # Series 2 numbers channels 101..164
        self._channel_numbers: dict[str, int] = {}
        self._channels_from_projector = False

    async def device_info(self) -> ProjectorInfo:
        info = await self.client.device_info()
        return ProjectorInfo(self.manufacturer, info.model, info.version, info.serial)

    async def close(self) -> None:
        await self.client.close()

    # -- polling ------------------------------------------------------------

    async def _query(self, key: str) -> p.Message | None:
        """Ask one value; None if the model does not support it."""
        if key in self._unsupported:
            return None
        try:
            return await self.client.request(key)
        except ProjectorTimeout as err:
            if key == "PWR":
                await self.client.close()  # reconnect on the next poll
                raise
            _LOGGER.info("%s: %s – wird nicht mehr abgefragt", self.host, err)
            self._unsupported.add(key)
            return None
        except ProjectorCommandError as err:
            _LOGGER.debug("%s: %s", self.host, err)
            if "unknown" in str(err).lower() or "invalid" in str(err).lower():
                _LOGGER.info("%s: %s wird nicht unterstützt (%s)", self.host, key, err)
                self._unsupported.add(key)
            return None

    async def update_power(self, d: ProjectorData) -> None:
        if (m := await self._query("PWR")) is not None:
            d.power, d.power_raw = m.number, m.data
        if (m := await self._query("PWR+STAT")) is not None:
            d.power_status, d.power_status_raw = m.number, m.data
        if d.state == PWR_COOLING:
            m = await self._query("PWR+COOL")
            d.cooldown = m.number if m is not None else None
        else:
            d.cooldown = None

    async def update_rest(self, d: ProjectorData) -> None:
        if (m := await self._query("SHU")) is not None:
            d.shutter = m.number
        if (m := await self._query("CHA")) is not None:
            d.channel = self._channel_name(m)
        if (m := await self._query("ITP")) is not None:
            d.pattern = _pattern_name(m)
            d.pattern_known = True

    async def read_lists(self, d: ProjectorData) -> None:
        self._unsupported.clear()  # give skipped queries another chance now and then
        numbers: dict[str, int] = {}
        try:
            channels = await self.client.request_list("CHA")
        except ProjectorCommandError as err:
            _LOGGER.debug("%s: no channel list: %s", self.host, err)
            channels = []
        self._channels_from_projector = bool(channels)
        if not channels:
            # Series 2: numbered channels, names via (NAM+CALL?) -> (NAM+CALL!"Name" 00001)
            try:
                replies = await self.client.request_all("NAM+CALL")
            except ProjectorCommandError as err:
                _LOGGER.debug("%s: no channel names: %s", self.host, err)
                replies = []
            for m in replies:
                name = (m.text or "").strip()
                nums = [int(x) for x in m.params if x.isdigit()]
                if not name or not nums:
                    continue
                if name in numbers:
                    name = f"{name} ({nums[-1]})"
                numbers[name] = nums[-1]
            channels = list(numbers)
        if not channels:
            channels = self._configured_channels or list(DEFAULT_CHANNELS)
            numbers = {name: i + 1 for i, name in enumerate(channels)}
        self._channel_numbers = numbers
        d.channels = channels
        try:
            patterns = await self.client.request_list("ITP")
        except ProjectorCommandError as err:
            _LOGGER.debug("%s: no test pattern list: %s", self.host, err)
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
        for name, num in self._channel_numbers.items():
            if num == number:
                return name
        return str(number)

    # -- commands -----------------------------------------------------------

    async def set_power(self, option: str) -> None:
        await self.client.set(f"PWR {_POWER[option]}")

    async def set_shutter(self, closed: bool) -> None:
        await self.client.set(f"SHU {1 if closed else 0}")

    async def set_channel(self, name: str) -> None:
        if self._numeric_channels and not self._channels_from_projector:
            number = self._channel_numbers.get(name) or int(name)
            await self.client.set(f"CHA {number + self._channel_offset}")
        else:
            await self.client.set(f"CHA {p.quote(name)}")

    async def set_pattern(self, name: str | None) -> None:
        if name is None:
            try:
                await self.client.set('ITP ""')
            except ProjectorCommandError:
                await self.client.set("ITP 0")  # older software: 0 = no test pattern
        else:
            await self.client.set(f"ITP {p.quote(name)}")

    def is_read_command(self, command: str) -> bool:
        return p.is_request(command)

    async def send_raw(self, command: str) -> list[str]:
        return await self.client.raw(command)


_POWER = {"standby": 3, "lamp_off": 0, "lamp_on": 1}


def _pattern_name(m: p.Message) -> str | None:
    """``(ITP!0)``, ``(ITP!000 "Testpattern Off")``, ``(ITP!"")`` = off; else the name."""
    if m.number == 0:
        return None
    if '"' in m.data:
        name = m.text
        return None if not name or name.strip().lower() in _OFF_NAMES else name
    if not m.params:
        return None
    return m.params[0]
