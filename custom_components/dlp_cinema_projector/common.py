"""Shared data structures and errors (no Home Assistant imports)."""

from __future__ import annotations

from dataclasses import dataclass, field

# Normalized power values (Christie PWR codes, Barco is mapped onto them)
PWR_LIGHT_OFF = 0
PWR_ON = 1
PWR_STANDBY = 3
PWR_HIBERNATE = -2
PWR_COOLING = 10
PWR_WARMING = 11

POWER_STATES = {
    PWR_LIGHT_OFF: "lamp_off",
    PWR_ON: "lamp_on",
    PWR_STANDBY: "standby",
    PWR_HIBERNATE: "hibernate",
    PWR_COOLING: "cooling",
    PWR_WARMING: "warming_up",
}


class ProjectorError(Exception):
    """Connection or protocol problem."""


class ProjectorCommandError(ProjectorError):
    """The projector rejected a command."""


class ProjectorTimeout(ProjectorError):
    """The projector did not answer (but the connection is up)."""


class ProjectorAuthError(ProjectorError):
    """Login was rejected."""


@dataclass(slots=True)
class ProjectorInfo:
    manufacturer: str
    model: str
    version: str | None = None
    serial: str | None = None


@dataclass(slots=True)
class ProjectorData:
    power: int | None = None  # target state (PWR? on Christie, lamp on/off on Barco)
    power_status: int | None = None  # actual state incl. warm-up/cool-down, if known
    power_raw: str | None = None
    power_status_raw: str | None = None
    cooldown: int | None = None
    shutter: int | None = None  # 0 open, 1 closed, None unknown
    channel: str | None = None
    channels: list[str] = field(default_factory=list)
    pattern: str | None = None  # None = no test pattern
    pattern_known: bool = False
    patterns: list[str] = field(default_factory=list)

    @property
    def state(self) -> int | None:
        """Best value for the actual power state."""
        if self.power_status is not None and self.power_status in POWER_STATES:
            return self.power_status
        return self.power
