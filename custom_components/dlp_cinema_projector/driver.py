"""Interface every manufacturer driver implements (no Home Assistant imports)."""

from __future__ import annotations

from .common import ProjectorData, ProjectorInfo


class Driver:
    """One projector connection. All methods raise ProjectorError subclasses."""

    manufacturer: str = ""
    power_options: list[str] = []  # subset of standby / lamp_off / lamp_on
    has_status: bool = False  # warm-up / cool-down status sensor
    has_patterns: bool = False  # test pattern select

    async def device_info(self) -> ProjectorInfo:
        raise NotImplementedError

    async def close(self) -> None:
        raise NotImplementedError

    async def update_power(self, data: ProjectorData) -> None:
        """Read the power state into data."""
        raise NotImplementedError

    async def update_rest(self, data: ProjectorData) -> None:
        """Read shutter, channel and test pattern into data."""
        raise NotImplementedError

    async def read_lists(self, data: ProjectorData) -> None:
        """Read the channel (and test pattern) lists into data."""
        raise NotImplementedError

    async def set_power(self, option: str) -> None:
        raise NotImplementedError

    async def set_shutter(self, closed: bool) -> None:
        raise NotImplementedError

    async def set_channel(self, name: str) -> None:
        raise NotImplementedError

    async def set_pattern(self, name: str | None) -> None:
        """None switches the test pattern off."""
        raise NotImplementedError

    def is_read_command(self, command: str) -> bool:
        """True if a raw command only reads (allowed in read-only mode)."""
        return False

    async def send_raw(self, command: str) -> list[str]:
        raise NotImplementedError
