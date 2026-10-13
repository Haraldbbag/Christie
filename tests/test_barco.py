"""Barco protocol and driver tests against the simulator (no Home Assistant needed).

    python3 tests/test_barco.py
"""

import asyncio
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import fake_barco  # noqa: E402  (registers the package stub)
from dlp_cinema_projector import barco_protocol as b  # noqa: E402
from dlp_cinema_projector.barco_driver import BarcoDriver  # noqa: E402
from dlp_cinema_projector.common import ProjectorCommandError, ProjectorData  # noqa: E402


def test_protocol() -> None:
    # Examples from the Barco document (addresses as given there)
    assert b.frame(b"\x76\x9a", 0x00).hex() == "fe00769a10ff"  # lamp read
    assert b.frame(b"\x21\x42", 0x01).hex() == "fe01214264ff"  # shutter read
    assert b.frame(b"\x23\x42\x00", 0x01).hex() == "fe0123420066ff"  # shutter close
    assert b.frame(b"\x22\x42\x00", 0x01).hex() == "fe0122420065ff"  # shutter open
    assert b.frame(b"\xe8\x05\x02", 0x01).hex() == "fe01e80502f0ff"  # button read macro
    assert b.frame(b"\x00\x03\x02\x76\x1a\x01", 0x00).hex() == "fe000003 02761a0196ff".replace(" ", "")
    # (The lamp-on example in the document shows checksum 91 for address 01 - that
    #  is the value for address 00; address + bytes = 92.)
    assert b.frame(b"\x76\x1a\x01", 0x00).hex() == "fe00761a0191ff"
    # escaping of 80 / FE / FF, including the checksum
    assert b.escape(b"\x80\xfe\xff\x10") == b"\x80\x00\x80\x7e\x80\x7f\x10"
    assert b.frame(b"\xfe", 0x00) == b"\xfe\x00\x80\x7e\x80\x7e\xff"
    parser = b.StreamParser()
    answer = b.frame(b"\xe8\x05\x02ABC\x00", 0x01)
    assert answer[-2] == 0xB6  # checksum from the document
    assert parser.feed(b"junk" + answer[:4]) == []
    assert parser.feed(answer[4:]) == [(1, b"\xe8\x05\x02ABC\x00")]
    assert parser.feed(b.frame(b"\xfe\x80")) == [(0, b"\xfe\x80")]
    bad = isinstance(parser.feed(b"\xfe\x00\x76\x9a\x11\xff")[0], b.FrameError)
    assert bad
    assert b.cstrings(b"Flat\x00Scope\x00\x00Pre") == ["Flat", "Scope", "", "Pre"]
    assert b.parse_hex("76 9a") == b"\x76\x9a" and b.parse_hex("E8.05") == b"\xe8\x05"


async def _driver(range_read: bool, port: int) -> None:
    st, server = await fake_barco.start("127.0.0.1", port, fake_barco.State(range_read))
    drv = BarcoDriver("127.0.0.1", port, "Kinoton")
    d = ProjectorData()
    try:
        info = await drv.device_info()
        assert info.manufacturer == "Kinoton"
        await drv.update_power(d)
        await drv.read_lists(d)
        await drv.update_rest(d)
        assert d.power == 0 and d.shutter == 1 and d.channel == "Flat", d
        assert d.channels == ["Flat", "Scope", "Preshow"], d.channels
        await drv.set_power("lamp_on")
        await drv.set_shutter(False)
        await drv.set_channel("Scope")
        await drv.update_power(d)
        await drv.update_rest(d)
        assert d.power == 1 and d.shutter == 0 and d.channel == "Scope", d
        try:
            await drv.set_channel("Gibt es nicht")
        except ProjectorCommandError:
            pass
        else:
            raise AssertionError("expected NACK")
        assert drv.is_read_command("76 9A") and not drv.is_read_command("76 1A 01")
        assert await drv.send_raw("21 42") == ["00 06", "21 42 01"]
        # connection drop -> reconnect
        await drv.client._disconnect()
        await drv.update_power(d)
        assert d.power == 1
    finally:
        await drv.close()
        server.close()


if __name__ == "__main__":
    test_protocol()
    asyncio.run(_driver(True, 15300))
    asyncio.run(_driver(False, 15301))
    print("all tests passed")
