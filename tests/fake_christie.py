"""Simulated Christie projector (CineLife-style serial API on TCP).

    python3 tests/fake_christie.py [host] [port] [--series2]

--series2 simulates an older projector without PNG/PWR+STAT/CHA?L that uses
numbered channels and test patterns.
Importing this module also registers a package stub so the client can be
imported without Home Assistant.
"""

from __future__ import annotations

import asyncio
import pathlib
import sys
import types

_PKG = pathlib.Path(__file__).resolve().parents[1] / "custom_components" / "christie"
if "christie" not in sys.modules:
    pkg = types.ModuleType("christie")
    pkg.__path__ = [str(_PKG)]
    sys.modules["christie"] = pkg

from christie import protocol as p  # noqa: E402

PATTERNS = ["DC2K Framing Green", "DC2K Full White", "Grey (50%)"]
CHANNELS = ["Media Block Flat", "Media Block Scope", "HDMI A", "HDMI B", "HDMI 3D LR"]


class State:
    def __init__(self, series2: bool = False, user: str | None = None, password: str = "") -> None:
        self.series2 = series2
        self.user, self.password = user, password
        self.power = 3
        self.status = 3
        self.shutter = 1
        self.channel = CHANNELS[0]
        self.pattern: str | None = None
        self.log: list[str] = []
        self.logged_in = user is None
        self.warm_task: asyncio.Task | None = None


def _err(text: str) -> str:
    return f'(65535 00000 ERR00005 "{text}")'


def handle(st: State, raw: str) -> list[str]:
    st.log.append(raw)
    m = p.parse(raw)
    key, kind = m.key, m.kind
    if key == "UID":
        if kind == "?":
            return [f"(UID!{20 if st.logged_in else 0:03d})"]
        if len(m.params) >= 2 and m.params[0] == st.user and m.params[1] == st.password:
            st.logged_in = True
            return []
        return [_err("UID: Invalid user or password")]
    if key == "PNG" and kind == "?":
        return [] if st.series2 else ["(PNG!060 002 003 001)"]
    if key == "SST+SERI" and kind == "?":
        if st.series2:
            return []
        return ['(SST+SERI!000 001 "PRJ123456" "Projector Serial")', '(SST+SERI!001 001 "LD-1" "Light Engine Serial")']
    if key == "PWR":
        if kind == "?":
            return [f"(PWR!{st.power:03d})"]
        st.power = int(m.params[0])
        st.status = 11 if st.power == 1 else (10 if st.power == 0 and st.status in (1, 11) else st.power)
        return [f"(PWR!{st.power:03d})"]
    if key == "PWR+STAT" and kind == "?":
        return [_err("PWR+STAT: Unknown command")] if st.series2 else [f"(PWR+STAT!{st.status:03d})"]
    if key == "PWR+COOL" and kind == "?":
        return ["(PWR+COOL!00480)"]
    if key == "SHU":
        if kind == "?":
            return [f"(SHU!{st.shutter})"]
        st.shutter = int(m.params[0])
        return []
    if key == "CHA":
        if kind == "?" and m.is_list:
            if st.series2:
                return [_err("CHA: Unknown command")]
            return [f'(CHA!L001 001 {i:03d} "{p.escape(n)}")' for i, n in enumerate(CHANNELS)] + ['(CHA!L111 "--END--")']
        if kind == "?":
            return [f"(CHA!{CHANNELS.index(st.channel) + 1:03d})" if st.series2 else f'(CHA! "{p.escape(st.channel)}")']
        val = m.params[0] if m.params else ""
        if val.isdigit():
            st.channel = CHANNELS[int(val) - 1]
        elif val in CHANNELS:
            st.channel = val
        else:
            return [_err("CHA: Invalid channel")]
        return []
    if key == "ITP":
        if not st.logged_in:
            return [_err("ITP: Access denied")]
        if kind == "?" and m.is_list:
            return [f'(ITP!L001 001 {i:03d} "{p.escape(n)}")' for i, n in enumerate(PATTERNS)] + ['(ITP!L111 "--END--")']
        if kind == "?":
            if st.pattern is None:
                return ["(ITP!0)"]
            return [f'(ITP!"{p.escape(st.pattern)}")']
        if not m.params:
            return [_err("ITP: Too Few Parameters")]
        val = m.params[0]
        if '""' in m.data and not st.series2:
            st.pattern = None
        elif val == "0" or val == "":
            if st.series2 and val == "":
                return [_err("ITP: Invalid pattern")]
            st.pattern = None
        elif val.isdigit():
            st.pattern = PATTERNS[int(val) - 1]
        elif val in PATTERNS:
            st.pattern = val
        else:
            return [_err("ITP: Invalid pattern")]
        return []
    if key == "HLP":
        return ['(HLP!"PWR - Power")', '(HLP!"SHU - Shutter")']
    return [_err(f"{m.code or '???'}: Unknown command")]


async def start(host: str, port: int, st: State | None = None):
    st = st or State()

    async def conn(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        parser = p.StreamParser()
        try:
            while chunk := await reader.read(4096):
                for raw in parser.feed(chunk):
                    for reply in handle(st, raw):
                        writer.write(reply.encode("latin-1"))
                await writer.drain()
        except ConnectionError:
            pass
        finally:
            writer.close()

    server = await asyncio.start_server(conn, host, port)
    return st, server


async def _main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    host = args[0] if args else "0.0.0.0"
    port = int(args[1]) if len(args) > 1 else 5000
    st, server = await start(host, port, State(series2="--series2" in sys.argv))
    print(f"Fake Christie projector on {host}:{port}")
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    asyncio.run(_main())
