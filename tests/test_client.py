"""Protocol and client tests against the simulator (no Home Assistant needed).

    python3 tests/test_client.py
"""

import asyncio
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import fake_christie  # noqa: E402  (registers the package stub)
from christie import protocol as p  # noqa: E402
from christie.client import (  # noqa: E402
    ChristieAuthError,
    ChristieClient,
    ChristieCommandError,
)


def test_protocol() -> None:
    # Examples from the CineLife 2.3.1 serial command reference
    m = p.parse('ITP!"DC2K Framing Green"')
    assert (m.code, m.kind, m.text) == ("ITP", "!", "DC2K Framing Green")
    m = p.parse('TMD+TIME! "12:18:49"')
    assert (m.key, m.text) == ("TMD+TIME", "12:18:49")
    m = p.parse("PWR!001")
    assert (m.code, m.kind, m.number) == ("PWR", "!", 1)
    m = p.parse('GAM!L001 001 000 "Gamma 2.4"')
    assert m.is_list and m.list_name == "Gamma 2.4"
    assert p.parse('ITP!L111 "--END--"').is_list_end
    m = p.parse('65535 00000 ERR00005 "ITP: Too Few Parameters"')
    assert m.error == "ITP: Too Few Parameters" and m.code == "ITP"
    m = p.parse('LPM! "0 080"')
    assert m.text == "0 080"
    m = p.parse("PWR!-02")
    assert m.number == -2
    # escaping and stream framing
    assert p.quote('A "b" (c)\\') == '"A \\"b\\" \\(c\\)\\\\"'
    parser = p.StreamParser()
    assert parser.feed(b'junk(CHA! "A \\(1\\)")(SH') == ['CHA! "A \\(1\\)"']
    assert parser.feed(b"U!0)\r\n") == ["SHU!0"]
    assert parser.feed(b"(PWR!0(PWR!1)") == ["PWR!1"]  # partial message discarded
    assert p.parse('CHA! "A \\(1\\)"').text == "A (1)"
    assert p.frame("PWR 1") == b"(PWR 1)" and p.frame("(PWR 1)") == b"(PWR 1)"
    assert p.is_request("PWR?") and p.is_request("(ITP?L)") and p.is_request("TMD+TIME?")
    assert not p.is_request("PWR 1") and not p.is_request("(SHU 0)")


async def _cinelife() -> None:
    st, server = await fake_christie.start("127.0.0.1", 15000)
    c = ChristieClient("127.0.0.1", 15000)
    try:
        info = await c.device_info()
        assert info.type_code == 60 and info.version == "2.3.1", info
        assert info.serial == "PRJ123456" and info.model.startswith("Series 3")
        assert (await c.request("PWR")).number == 3
        assert (await c.request("PWR+STAT")).number == 3
        await c.set("PWR 1")
        assert (await c.request("PWR+STAT")).number == 11
        assert (await c.request("CHA")).text == "Media Block Flat"
        assert await c.request_list("CHA") == fake_christie.CHANNELS
        await c.set(f"CHA {p.quote('HDMI A')}")
        assert (await c.request("CHA")).text == "HDMI A"
        try:
            await c.set(f"CHA {p.quote('Nope')}")
        except ChristieCommandError:
            pass
        else:
            raise AssertionError("expected error")
        assert await c.request_list("ITP") == fake_christie.PATTERNS
        await c.set(f"ITP {p.quote('Grey (50%)')}")
        assert (await c.request("ITP")).text == "Grey (50%)"
        await c.set('ITP ""')
        assert (await c.request("ITP")).number == 0
        await c.set("SHU 0")
        assert (await c.request("SHU")).number == 0
        replies = await c.raw("(HLP?)", wait=1, idle=0.3)
        assert len(replies) == 2, replies
        # connection drop -> automatic reconnect
        await c._disconnect()
        assert (await c.request("SHU")).number == 0
    finally:
        await c.close()
        server.close()


async def _series2() -> None:
    st, server = await fake_christie.start("127.0.0.1", 15001, fake_christie.State(series2=True))
    c = ChristieClient("127.0.0.1", 15001)
    try:
        info = await c.device_info()
        assert info.type_code is None and info.serial is None
        assert (await c.request("CHA")).number == 1
        try:
            await c.request_list("CHA")
        except ChristieCommandError:
            pass
        await c.set("CHA 3")
        assert (await c.request("CHA")).number == 3
        await c.set("ITP 2")
        assert (await c.request("ITP")).number is None
        await c.set("ITP 0")
        assert (await c.request("ITP")).number == 0
    finally:
        await c.close()
        server.close()


async def _auth() -> None:
    st, server = await fake_christie.start(
        "127.0.0.1", 15002, fake_christie.State(user="operator", password="secret")
    )
    try:
        bad = ChristieClient("127.0.0.1", 15002, "operator", "wrong")
        try:
            await bad.device_info()
        except ChristieAuthError:
            pass
        else:
            raise AssertionError("expected auth error")
        finally:
            await bad.close()
        good = ChristieClient("127.0.0.1", 15002, "operator", "secret")
        try:
            await good.device_info()
            assert await good.request_list("ITP") == fake_christie.PATTERNS
        finally:
            await good.close()
    finally:
        server.close()


if __name__ == "__main__":
    test_protocol()
    asyncio.run(_cinelife())
    asyncio.run(_series2())
    asyncio.run(_auth())
    print("all tests passed")
