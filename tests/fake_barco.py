"""Simulated Barco DP Series 2 projector (binary protocol on TCP).

    python3 tests/fake_barco.py [host] [port]

Importing this module also registers a package stub so the drivers can be
imported without Home Assistant.
"""

from __future__ import annotations

import asyncio
import pathlib
import sys
import types

_PKG = pathlib.Path(__file__).resolve().parents[1] / "custom_components" / "dlp_cinema_projector"
if "dlp_cinema_projector" not in sys.modules:
    pkg = types.ModuleType("dlp_cinema_projector")
    pkg.__path__ = [str(_PKG)]
    sys.modules["dlp_cinema_projector"] = pkg

from dlp_cinema_projector import barco_protocol as b  # noqa: E402

BUTTONS = ["Flat", "Scope", "", "Preshow", "Scope"]  # empty and duplicate on purpose


class State:
    def __init__(self, range_read: bool = True) -> None:
        self.lamp = 0
        self.shutter = 0  # Barco: 0 closed, 1 open
        self.macro = "Flat"
        self.range_read = range_read  # False: projector NACKs the from/to form
        self.log: list[str] = []


def handle(st: State, body: bytes) -> list[bytes]:
    st.log.append(b.to_hex(body))
    ack, nack = [b.ACK], [b.NACK]
    if body == b.LAMP_READ:
        return ack + [b.LAMP_READ + bytes([st.lamp])]
    if body[:2] == b.LAMP_WRITE and len(body) == 3:
        st.lamp = body[2]
        return ack
    if body == b.SHUTTER_READ:
        return ack + [b.SHUTTER_READ + bytes([st.shutter])]
    if body == b.SHUTTER_OPEN:
        st.shutter = 1
        return ack
    if body == b.SHUTTER_CLOSE:
        st.shutter = 0
        return ack
    if body == b.MACRO_READ:
        return ack + [b.MACRO_READ + b.cstring(st.macro)]
    if body[:2] == b.MACRO_EXECUTE:
        name = b.cstrings(body[2:])[0]
        if name not in BUTTONS or not name:
            return nack
        st.macro = name
        return ack
    if body[:2] == b.BUTTON_READ_MACRO:
        args = body[2:]
        if len(args) == 2:
            if not st.range_read:
                return nack
            first, last = args
            names = b"".join(b.cstring(BUTTONS[i - 1]) for i in range(first, min(last, len(BUTTONS)) + 1))
            return ack + [b.BUTTON_READ_MACRO + bytes([first, last]) + names]
        if len(args) == 1 and 1 <= args[0] <= len(BUTTONS):
            return ack + [b.BUTTON_READ_MACRO + args + b.cstring(BUTTONS[args[0] - 1])]
        return nack
    return nack


async def start(host: str, port: int, st: State | None = None):
    st = st or State()

    async def conn(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        parser = b.StreamParser()
        try:
            while chunk := await reader.read(4096):
                for item in parser.feed(chunk):
                    if isinstance(item, b.FrameError):
                        continue  # the projector ignores bad frames
                    for reply in handle(st, item[1]):
                        writer.write(b.frame(reply))
                await writer.drain()
        except ConnectionError:
            pass
        finally:
            writer.close()

    server = await asyncio.start_server(conn, host, port)
    return st, server


async def _main() -> None:
    host = sys.argv[1] if len(sys.argv) > 1 else "0.0.0.0"
    port = int(sys.argv[2]) if len(sys.argv) > 2 else 43728
    st, server = await start(host, port)
    print(f"Fake Barco projector on {host}:{port}")
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    asyncio.run(_main())
