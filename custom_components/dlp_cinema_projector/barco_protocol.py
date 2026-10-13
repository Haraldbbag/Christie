"""Barco DP (Series 1/2) binary protocol, also used by Kinoton DP projectors.

Frame:  FE <address> <command bytes> <data bytes> <checksum> FF
        checksum = (address + command + data) mod 256
        Bytes 80, FE, FF inside command/data/checksum are sent as 80 00, 80 7E, 80 7F.
Over Ethernet the address is 00. Every command is first answered with an
acknowledge (00 06) or no-acknowledge (00 15); read commands are then
answered with a frame that repeats the command bytes followed by the data.

Source: Barco "Communication Interface Barco DP Projectors" (TDE4313, rev. 5).
"""

from __future__ import annotations

START = 0xFE
STOP = 0xFF
ESC = 0x80
ADDRESS = 0x00

ACK = b"\x00\x06"
NACK = b"\x00\x15"

LAMP_READ = b"\x76\x9a"
LAMP_WRITE = b"\x76\x1a"
SHUTTER_READ = b"\x21\x42"
SHUTTER_OPEN = b"\x22\x42\x00"
SHUTTER_CLOSE = b"\x23\x42\x00"
MACRO_EXECUTE = b"\xe8\x81"
MACRO_READ = b"\xe8\x01"  # name of the last executed macro
BUTTON_READ_MACRO = b"\xe8\x05"  # macro names on the keypad buttons

# Commands that only read; allowed as raw commands in read-only mode.
READ_COMMANDS = (
    LAMP_READ,
    SHUTTER_READ,
    MACRO_READ,
    BUTTON_READ_MACRO,
    b"\x81\x04\x17",  # error/warning/notification counts
    b"\x67\x01",  # sleep mode read
    b"\x82\x00\x00\x00\x1a\x03",  # macro read (2)
)

_ESCAPES = {ESC: b"\x80\x00", START: b"\x80\x7e", STOP: b"\x80\x7f"}
_UNESCAPES = {0x00: ESC, 0x7E: START, 0x7F: STOP}


def checksum(address: int, body: bytes) -> int:
    return (address + sum(body)) & 0xFF


def escape(data: bytes) -> bytes:
    out = bytearray()
    for b in data:
        out += _ESCAPES.get(b, bytes([b]))
    return bytes(out)


def frame(body: bytes, address: int = ADDRESS) -> bytes:
    """Build a complete frame for command + data bytes."""
    return (
        bytes([START, address])
        + escape(body + bytes([checksum(address, body)]))
        + bytes([STOP])
    )


def cstring(text: str) -> bytes:
    return text.encode("latin-1", errors="replace") + b"\x00"


def cstrings(data: bytes) -> list[str]:
    """Split NUL-terminated strings (the last one may lack its terminator)."""
    parts = data.split(b"\x00")
    if parts and parts[-1] == b"":
        parts.pop()
    return [x.decode("latin-1") for x in parts]


def parse_hex(text: str) -> bytes:
    """'76 9A' / '769a' / '76.9A' -> bytes."""
    cleaned = "".join(ch for ch in text if ch.lower() in "0123456789abcdef")
    if not cleaned or len(cleaned) % 2:
        raise ValueError(f"Ungültige Hex-Bytes: {text!r}")
    return bytes.fromhex(cleaned)


def to_hex(data: bytes) -> str:
    return " ".join(f"{b:02X}" for b in data)


class FrameError(ValueError):
    """A received frame had a bad checksum."""


class StreamParser:
    """Collect frames from a byte stream; returns (address, body) tuples."""

    def __init__(self) -> None:
        self._buf: bytearray | None = None

    def feed(self, chunk: bytes) -> list[tuple[int, bytes] | FrameError]:
        out: list[tuple[int, bytes] | FrameError] = []
        for b in chunk:
            if b == START:
                self._buf = bytearray()  # a new start discards a partial frame
                continue
            if self._buf is None:
                continue
            if b == STOP:
                out.append(self._finish(bytes(self._buf)))
                self._buf = None
                continue
            self._buf.append(b)
        return out

    @staticmethod
    def _finish(raw: bytes) -> tuple[int, bytes] | FrameError:
        data = bytearray()
        i = 0
        while i < len(raw):
            b = raw[i]
            if b == ESC and i + 1 < len(raw):
                data.append(_UNESCAPES.get(raw[i + 1], raw[i + 1]))
                i += 2
                continue
            data.append(b)
            i += 1
        if len(data) < 2:
            return FrameError(f"Frame zu kurz: {to_hex(raw)}")
        address, body, check = data[0], bytes(data[1:-1]), data[-1]
        if checksum(address, body) != check:
            return FrameError(f"Prüfsumme falsch: {to_hex(bytes(data))}")
        return address, body
