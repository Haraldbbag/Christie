"""Async TCP client for Christie cinema projectors (no Home Assistant imports)."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import logging
import time

from . import protocol as p

_LOGGER = logging.getLogger(__name__)

CONNECT_TIMEOUT = 5.0
REPLY_TIMEOUT = 3.0  # wait for the reply to a request
ACK_TIMEOUT = 1.0  # sets are not always answered; wait this long for an error
LIST_IDLE = 1.0  # a list is complete when nothing arrives for this long
LIST_TIMEOUT = 15.0


class ChristieError(Exception):
    """Connection or protocol problem."""


class ChristieCommandError(ChristieError):
    """The projector answered with an error message."""


class ChristieTimeout(ChristieError):
    """The projector did not answer (but the connection is up)."""


class ChristieAuthError(ChristieError):
    """Login (UID) was rejected."""


@dataclass(slots=True)
class DeviceInfo:
    type_code: int | None = None
    version: str | None = None
    serial: str | None = None

    @property
    def model(self) -> str:
        return {
            60: "Series 3 (CineLife)",
            71: "Series 4 (CineLife+)",
        }.get(self.type_code or -1, f"Typ {self.type_code}" if self.type_code is not None else "Christie")


class ChristieClient:
    """One persistent connection, commands are serialized."""

    def __init__(
        self,
        host: str,
        port: int = 5000,
        username: str | None = None,
        password: str | None = None,
    ) -> None:
        self.host = host
        self.port = port
        self._username = username or None
        self._password = password or ""
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._reader_task: asyncio.Task | None = None
        self._queue: asyncio.Queue[p.Message] = asyncio.Queue()
        self._lock = asyncio.Lock()
        self._parser = p.StreamParser()

    # -- connection ---------------------------------------------------------

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
            raise ChristieError(f"Keine Verbindung zu {self.host}:{self.port}: {err}") from err
        self._parser = p.StreamParser()
        self._queue = asyncio.Queue()
        self._reader_task = asyncio.get_running_loop().create_task(self._read_loop())
        _LOGGER.debug("Connected to %s:%s", self.host, self.port)
        if self._username:
            await self._send(f"UID {p.quote(self._username)} {p.quote(self._password)}")
            msgs = await self._collect(lambda m: m.code == "UID" or m.error is not None, ACK_TIMEOUT)
            for m in msgs:
                if m.error:
                    raise ChristieAuthError(f"Anmeldung fehlgeschlagen: {m.error}")

    async def _read_loop(self) -> None:
        assert self._reader is not None
        try:
            while True:
                chunk = await self._reader.read(4096)
                if not chunk:
                    break
                for raw in self._parser.feed(chunk):
                    msg = p.parse(raw)
                    _LOGGER.debug("%s <- (%s)", self.host, raw)
                    self._queue.put_nowait(msg)
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

    async def _send(self, command: str) -> None:
        if not self.connected:
            raise ChristieError("Nicht verbunden")
        data = p.frame(command)
        _LOGGER.debug("%s -> %s", self.host, data.decode("latin-1"))
        assert self._writer is not None
        try:
            self._writer.write(data)
            await self._writer.drain()
        except OSError as err:
            await self._disconnect()
            raise ChristieError(f"Senden fehlgeschlagen: {err}") from err

    def _drain(self) -> None:
        while not self._queue.empty():
            msg = self._queue.get_nowait()
            _LOGGER.debug("%s: unsolicited (%s)", self.host, msg.raw)

    async def _next(self, timeout: float) -> p.Message | None:
        if timeout <= 0:
            return None
        try:
            return await asyncio.wait_for(self._queue.get(), timeout)
        except asyncio.TimeoutError:
            return None

    async def _collect(self, match, timeout: float) -> list[p.Message]:
        """Wait for the first matching message (or timeout)."""
        end = time.monotonic() + timeout
        out: list[p.Message] = []
        while (msg := await self._next(end - time.monotonic())) is not None:
            if match(msg):
                out.append(msg)
                break
            _LOGGER.debug("%s: ignored (%s)", self.host, msg.raw)
        return out

    async def _run(self, func):
        """Run func under the lock; reconnect once if the connection dropped."""
        async with self._lock:
            for attempt in (1, 2):
                try:
                    await self._connect()
                    self._drain()
                    return await func()
                except ChristieAuthError:
                    await self._disconnect()
                    raise
                except (ChristieCommandError, ChristieTimeout):
                    raise
                except ChristieError:
                    await self._disconnect()
                    if attempt == 2:
                        raise

    # -- commands -----------------------------------------------------------

    @staticmethod
    def _key(command: str) -> tuple[str, str | None]:
        body = command.strip().lstrip("(")
        code = body[:3].upper()
        sub = body[4:8].upper() if body[3:4] == "+" else None
        return code, sub

    async def request(self, key: str, args: str = "") -> p.Message:
        """Send ``(KEY?)`` and return the reply."""
        code, sub = self._key(key)
        command = f"{key}?{(' ' + args) if args else ''}"

        def match(m: p.Message) -> bool:
            if m.error is not None:
                return True
            return m.code == code and m.sub == sub and m.kind == "!" and not m.is_list

        async def run() -> p.Message:
            await self._send(command)
            msgs = await self._collect(match, REPLY_TIMEOUT)
            if not msgs:
                if not self.connected:
                    raise ChristieError("Verbindung getrennt")
                raise ChristieTimeout(f"Keine Antwort auf ({command})")
            if msgs[0].error is not None:
                raise ChristieCommandError(f"({command}): {msgs[0].error}")
            return msgs[0]

        return await self._run(run)

    async def request_list(self, key: str) -> list[str]:
        """Send ``(KEY?L)`` and return the names of all entries."""
        code, sub = self._key(key)

        async def run() -> list[str]:
            await self._send(f"{key}?L")
            names: list[str] = []
            end = time.monotonic() + LIST_TIMEOUT
            idle = REPLY_TIMEOUT  # wait longer for the first entry
            while True:
                msg = await self._next(min(idle, end - time.monotonic()))
                if msg is None:
                    break
                if msg.error is not None:
                    raise ChristieCommandError(f"({key}?L): {msg.error}")
                if msg.code != code or msg.sub != sub or not msg.is_list:
                    _LOGGER.debug("%s: ignored (%s)", self.host, msg.raw)
                    continue
                if msg.is_list_end:
                    break
                if (name := msg.list_name) is not None:
                    names.append(name)
                idle = LIST_IDLE
            return names

        return await self._run(run)

    async def set(self, command: str) -> p.Message | None:
        """Send a set command; raise on an error reply, return the reply if any."""
        code, sub = self._key(command)

        def match(m: p.Message) -> bool:
            return m.error is not None or (m.code == code and m.sub == sub and m.kind == "!")

        async def run() -> p.Message | None:
            await self._send(command)
            msgs = await self._collect(match, ACK_TIMEOUT)
            if msgs and msgs[0].error is not None:
                raise ChristieCommandError(f"({command}): {msgs[0].error}")
            return msgs[0] if msgs else None

        return await self._run(run)

    async def raw(self, command: str, wait: float = 3.0, idle: float = 0.7) -> list[str]:
        """Send anything, return every message received until the line is quiet."""

        async def run() -> list[str]:
            await self._send(command)
            out: list[str] = []
            end = time.monotonic() + max(wait, 0.5) + 30  # hard cap for long help listings
            timeout = wait
            while (msg := await self._next(min(timeout, end - time.monotonic()))) is not None:
                out.append(f"({msg.raw})")
                timeout = idle
            return out

        return await self._run(run)

    async def device_info(self) -> DeviceInfo:
        """Identify the projector. Raises ChristieError if it does not answer at all."""
        info = DeviceInfo()
        try:
            ping = await self.request("PNG")
            nums = [int(x) for x in ping.params if x.lstrip("-").isdigit()]
            if nums:
                info.type_code = nums[0]
                info.version = ".".join(str(n) for n in nums[1:]) or None
        except ChristieAuthError:
            raise
        except ChristieCommandError:
            pass
        except ChristieError:
            # No PNG on this model? Fall back to the power state as "alive" check.
            await self.request("PWR")
        try:
            info.serial = await self._serial()
        except ChristieAuthError:
            raise
        except ChristieError as err:
            _LOGGER.debug("%s: no serial number: %s", self.host, err)
        return info

    async def _serial(self) -> str | None:
        """Best effort: the projector serial number from ``(SST+SERI?)``."""

        async def run() -> str | None:
            await self._send("SST+SERI?")
            best: str | None = None
            end = time.monotonic() + 4
            timeout = REPLY_TIMEOUT
            while (msg := await self._next(min(timeout, end - time.monotonic()))) is not None:
                timeout = 0.5
                if msg.error is not None or msg.code != "SST":
                    continue
                params = msg.params
                # (SST+SERI!000 001 "value" "description")
                if len(params) >= 3:
                    value = params[2].strip()
                    desc = (params[3] if len(params) > 3 else "").lower()
                    if value and (best is None or "projector" in desc or "product" in desc):
                        best = value
                        if "projector" in desc or "product" in desc:
                            break
            return best

        return await self._run(run)
