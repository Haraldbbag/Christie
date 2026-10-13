"""Christie cinema projector serial protocol (ASCII, port 5000).

Messages are framed by round brackets:

    (CODE[+SUBC] [?|!][L]data)

* ``(PWR 1)``                   set
* ``(PWR?)`` / ``(TMD+TIME?)``   request
* ``(PWR!001)``                  reply
* ``(ITP!L001 001 000 "Name")``  list reply entry, list ends with ``"--END--"``
* ``(65535 00000 ERR00005 "ITP: Too Few Parameters")``  error

Inside text, ``" \\ ( )`` are escaped with a backslash.
This module has no Home Assistant dependency so it can be tested standalone.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import re

LIST_END = "--END--"

_REPLY_RE = re.compile(
    r"^(?P<code>[A-Za-z]{3})(?:\+(?P<sub>[A-Za-z0-9]{4}))?\s*(?P<kind>[!?])?(?P<list>L(?=[\s\d\"-]|$))?\s*(?P<data>.*)$",
    re.S,
)
_ERROR_RE = re.compile(r"^\s*(?P<a>\d+)\s+(?P<b>\d+)\s+ERR(?P<num>\d+)\s*(?P<text>.*)$", re.S)


def escape(text: str) -> str:
    """Escape a text parameter (without the surrounding quotes)."""
    return (
        text.replace("\\", "\\\\").replace('"', '\\"').replace("(", "\\(").replace(")", "\\)")
    )


def quote(text: str) -> str:
    return f'"{escape(text)}"'


def frame(command: str) -> bytes:
    """Wrap a command in brackets unless it already is."""
    command = command.strip()
    if not (command.startswith("(") and command.endswith(")")):
        command = f"({command})"
    return command.encode("latin-1", errors="replace")


def tokenize(data: str) -> list[str]:
    """Split parameters at spaces; quoted strings become one (unescaped) token."""
    tokens: list[str] = []
    i, n = 0, len(data)
    while i < n:
        ch = data[i]
        if ch.isspace():
            i += 1
            continue
        if ch == '"':
            i += 1
            buf = []
            while i < n and data[i] != '"':
                if data[i] == "\\" and i + 1 < n:
                    i += 1
                buf.append(data[i])
                i += 1
            i += 1  # closing quote
            tokens.append("".join(buf))
            continue
        start = i
        while i < n and not data[i].isspace():
            i += 1
        tokens.append(data[start:i])
    return tokens


@dataclass(slots=True)
class Message:
    """One parsed message from the projector."""

    raw: str
    code: str | None = None
    sub: str | None = None
    kind: str | None = None  # "!" reply, "?" request (echo), None set/other
    is_list: bool = False
    data: str = ""
    params: list[str] = field(default_factory=list)
    error: str | None = None  # error text, if this is an error message
    error_code: int | None = None

    @property
    def key(self) -> str | None:
        if self.code is None:
            return None
        return f"{self.code}+{self.sub}" if self.sub else self.code

    @property
    def text(self) -> str | None:
        """The (last) quoted text parameter, else the first parameter."""
        quoted = re.findall(r'"((?:\\.|[^"\\])*)"', self.data)
        if quoted:
            return tokenize(f'"{quoted[-1]}"')[0]
        return self.params[0] if self.params else None

    @property
    def number(self) -> int | None:
        if not self.params:
            return None
        try:
            return int(self.params[0])
        except ValueError:
            return None

    @property
    def list_name(self) -> str | None:
        """Name of a list entry (``(XXX!L001 001 000 "Name")``)."""
        return self.text if self.is_list else None

    @property
    def is_list_end(self) -> bool:
        return self.is_list and self.text == LIST_END


def parse(raw: str) -> Message:
    """Parse the content between the brackets of one message."""
    body = raw.strip()
    err = _ERROR_RE.match(body)
    if err:
        text_tokens = tokenize(err.group("text"))
        text = text_tokens[-1] if text_tokens else err.group("text").strip()
        msg = Message(raw=raw, error=text or f"ERR{err.group('num')}", error_code=int(err.group("num")))
        # "ITP: Too Few Parameters" -> code ITP
        m = re.match(r"^([A-Za-z]{3})(?:\+([A-Za-z0-9]{4}))?\s*:", text or "")
        if m:
            msg.code = m.group(1).upper()
            msg.sub = m.group(2).upper() if m.group(2) else None
        return msg
    m = _REPLY_RE.match(body)
    if not m:
        return Message(raw=raw, data=body, params=tokenize(body))
    data = m.group("data") or ""
    return Message(
        raw=raw,
        code=m.group("code").upper(),
        sub=m.group("sub").upper() if m.group("sub") else None,
        kind=m.group("kind"),
        is_list=bool(m.group("list")),
        data=data,
        params=tokenize(data),
    )


class StreamParser:
    """Collect complete ``(...)`` messages from a byte stream."""

    def __init__(self) -> None:
        self._buf: list[str] | None = None
        self._escape = False
        self._quoted = False

    def feed(self, chunk: bytes) -> list[str]:
        out: list[str] = []
        for ch in chunk.decode("latin-1"):
            if self._buf is None:
                if ch == "(":
                    self._buf = []
                    self._escape = self._quoted = False
                continue
            if self._escape:
                self._buf.append(ch)
                self._escape = False
                continue
            if ch == "\\":
                self._buf.append(ch)
                self._escape = True
                continue
            if ch == '"':
                self._quoted = not self._quoted
                self._buf.append(ch)
                continue
            if ch == "(" and not self._quoted:
                # New start before the end: discard the partial message.
                self._buf = []
                continue
            if ch == ")" and not self._quoted:
                out.append("".join(self._buf))
                self._buf = None
                continue
            self._buf.append(ch)
        return out


def is_request(command: str) -> bool:
    """True if a raw command only reads (``XXX?``, ``XXX+YYYY?``, ``XXX?L``)."""
    body = command.strip()
    if body.startswith("("):
        body = body[1:]
    return re.match(r"^[A-Za-z]{3}(?:\+[A-Za-z0-9]{4})?\s*\?", body) is not None
