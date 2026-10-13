"""Barco / Kinoton DP Series 2 driver (binary protocol on TCP 43728)."""

from __future__ import annotations

import asyncio
import logging
import time

from . import barco_protocol as b
from .common import (
    PWR_LIGHT_OFF,
    PWR_ON,
    ProjectorCommandError,
    ProjectorData,
    ProjectorError,
    ProjectorInfo,
    ProjectorTimeout,
)
from .driver import Driver

_LOGGER = logging.getLogger(__name__)

CONNECT_TIMEOUT = 5.0
ACK_TIMEOUT = 3.0
ANSWER_TIMEOUT = 5.0
MAX_BUTTONS = 16


class BarcoClient:
    """One persistent connection; the projector handles one request at a time."""

    def __init__(self, host: str, port: int) -> None:
        self.host = host
        self.port = port
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._reader_task: asyncio.Task | None = None
        self._queue: asyncio.Queue[tuple[int, bytes] | b.FrameError] = asyncio.Queue()
        self._lock = asyncio.Lock()

    @property
    def connected(self) -> bool:
        return self._writer is not None and not self._writer.is_closing()

    async def _connect(self) -> None:
        if self.connected:
            return
        await self._disconnect()
        try:
            self._reader, self._writer = await asyncio.wait_for(
                asyncio.open_connection(self.host, self.port), CONNECT_TIMEOUT
            )
        except (OSError, asyncio.TimeoutError) as err:
            raise ProjectorError(f"Keine Verbindung zu {self.host}:{self.port}: {err}") from err
        self._queue = asyncio.Queue()
        self._reader_task = asyncio.get_running_loop().create_task(self._read_loop())
        _LOGGER.debug("Connected to %s:%s", self.host, self.port)

    async def _read_loop(self) -> None:
        assert self._reader is not None
        parser = b.StreamParser()
        try:
            while chunk := await self._reader.read(4096):
                for item in parser.feed(chunk):
                    if isinstance(item, b.FrameError):
                        _LOGGER.debug("%s <- %s", self.host, item)
                    else:
                        _LOGGER.debug("%s <- %s", self.host, b.to_hex(item[1]))
                    self._queue.put_nowait(item)
        except (OSError, asyncio.CancelledError):
            pass
        finally:
            if self._writer is not None:
                self._writer.close()

    async def _disconnect(self) -> None:
        if self._reader_task is not None:
            self._reader_task.cancel()
            self._reader_task = None
        if self._writer is not None:
            try:
                self._writer.close()
                await asyncio.wait_for(self._writer.wait_closed(), 2)
            except (OSError, asyncio.TimeoutError):
                pass
        self._reader = self._writer = None

    async def close(self) -> None:
        async with self._lock:
            await self._disconnect()

    async def _next(self, timeout: float) -> bytes | None:
        """Next valid frame body, or None on timeout."""
        end = time.monotonic() + timeout
        while (left := end - time.monotonic()) > 0:
            try:
                item = await asyncio.wait_for(self._queue.get(), left)
            except asyncio.TimeoutError:
                return None
            if isinstance(item, b.FrameError):
                continue
            return item[1]
        return None

    async def _exchange(self, body: bytes, answer: bytes | None) -> bytes | None:
        """Send body, wait for ACK, then (if answer is given) for the reply starting with it."""
        while not self._queue.empty():
            self._queue.get_nowait()
        assert self._writer is not None
        data = b.frame(body)
        _LOGGER.debug("%s -> %s", self.host, b.to_hex(data))
        try:
            self._writer.write(data)
            await self._writer.drain()
        except OSError as err:
            await self._disconnect()
            raise ProjectorError(f"Senden fehlgeschlagen: {err}") from err
        end = time.monotonic() + ACK_TIMEOUT
        while True:
            reply = await self._next(end - time.monotonic())
            if reply is None:
                if not self.connected:
                    raise ProjectorError("Verbindung getrennt")
                raise ProjectorTimeout(f"Keine Quittung auf {b.to_hex(body)}")
            if reply == b.NACK:
                raise ProjectorCommandError(f"Befehl {b.to_hex(body)} abgelehnt (NACK)")
            if reply == b.ACK:
                break
            _LOGGER.debug("%s: ignored %s", self.host, b.to_hex(reply))
        if answer is None:
            return None
        end = time.monotonic() + ANSWER_TIMEOUT
        while True:
            reply = await self._next(end - time.monotonic())
            if reply is None:
                raise ProjectorTimeout(f"Keine Antwort auf {b.to_hex(body)}")
            if reply.startswith(answer):
                return reply[len(answer):]
            _LOGGER.debug("%s: ignored %s", self.host, b.to_hex(reply))

    async def _run(self, body: bytes, answer: bytes | None) -> bytes | None:
        async with self._lock:
            for attempt in (1, 2):
                try:
                    await self._connect()
                    return await self._exchange(body, answer)
                except (ProjectorCommandError, ProjectorTimeout):
                    raise
                except ProjectorError:
                    await self._disconnect()
                    if attempt == 2:
                        raise
        return None

    async def read(self, command: bytes, data: bytes = b"") -> bytes:
        """Read command; returns the data after the repeated command bytes."""
        result = await self._run(command + data, command)
        assert result is not None
        return result

    async def write(self, command: bytes, data: bytes = b"") -> None:
        await self._run(command + data, None)

    async def raw(self, body: bytes, wait: float = 3.0, idle: float = 0.7) -> list[str]:
        """Send any body, return every frame received until the line is quiet."""
        async with self._lock:
            await self._connect()
            while not self._queue.empty():
                self._queue.get_nowait()
            assert self._writer is not None
            self._writer.write(b.frame(body))
            await self._writer.drain()
            out: list[str] = []
            timeout = wait
            while (reply := await self._next(timeout)) is not None:
                out.append(b.to_hex(reply))
                timeout = idle
            return out


class BarcoDriver(Driver):
    manufacturer = "Barco"
    power_options = ["lamp_off", "lamp_on"]
    has_status = False
    has_patterns = False

    def __init__(self, host: str, port: int, manufacturer: str = "Barco") -> None:
        self.client = BarcoClient(host, port)
        self.host = host
        self.manufacturer = manufacturer
        self._macro_ok = True

    async def device_info(self) -> ProjectorInfo:
        await self.client.read(b.LAMP_READ)  # proves the projector answers
        return ProjectorInfo(self.manufacturer, "DP Series 2")

    async def close(self) -> None:
        await self.client.close()

    async def update_power(self, d: ProjectorData) -> None:
        data = await self.client.read(b.LAMP_READ)
        lamp = data[0] if data else None
        d.power_raw = b.to_hex(data)
        d.power = {0: PWR_LIGHT_OFF, 1: PWR_ON}.get(lamp)

    async def update_rest(self, d: ProjectorData) -> None:
        data = await self.client.read(b.SHUTTER_READ)
        # Barco: 0 closed, 1 open, 2 undetermined -> 1 closed, 0 open, None
        d.shutter = {0: 1, 1: 0}.get(data[0]) if data else None
        if self._macro_ok:
            try:
                names = b.cstrings(await self.client.read(b.MACRO_READ))
            except ProjectorCommandError as err:
                _LOGGER.info("%s: letztes Makro nicht lesbar: %s", self.host, err)
                self._macro_ok = False
            else:
                d.channel = names[0] if names and names[0] else None

    async def read_lists(self, d: ProjectorData) -> None:
        self._macro_ok = True
        names: list[str] = []
        try:
            # All buttons in one request: data = from, to; answer = from, to, names
            data = await self.client.read(b.BUTTON_READ_MACRO, bytes([1, MAX_BUTTONS]))
            names = b.cstrings(data[2:])
        except (ProjectorCommandError, ProjectorTimeout) as err:
            _LOGGER.debug("%s: button range read failed (%s), reading one by one", self.host, err)
            for button in range(1, MAX_BUTTONS + 1):
                try:
                    data = await self.client.read(b.BUTTON_READ_MACRO, bytes([button]))
                except (ProjectorCommandError, ProjectorTimeout):
                    break
                names.extend(b.cstrings(data[1:])[:1])
        channels: list[str] = []
        for name in names:
            if name.strip() and name not in channels:
                channels.append(name)
        d.channels = channels

    async def set_power(self, option: str) -> None:
        await self.client.write(b.LAMP_WRITE, b"\x01" if option == "lamp_on" else b"\x00")

    async def set_shutter(self, closed: bool) -> None:
        await self.client.write(b.SHUTTER_CLOSE if closed else b.SHUTTER_OPEN)

    async def set_channel(self, name: str) -> None:
        await self.client.write(b.MACRO_EXECUTE, b.cstring(name))

    async def set_pattern(self, name: str | None) -> None:
        raise ProjectorCommandError("Barco: Testbilder werden nicht unterstützt")

    def is_read_command(self, command: str) -> bool:
        try:
            body = b.parse_hex(command)
        except ValueError:
            return False
        return any(body.startswith(c) for c in b.READ_COMMANDS)

    async def send_raw(self, command: str) -> list[str]:
        try:
            body = b.parse_hex(command)
        except ValueError as err:
            raise ProjectorCommandError(str(err)) from err
        return await self.client.raw(body)
