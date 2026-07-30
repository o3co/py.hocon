"""Java-properties parsing for ``.properties`` includes.

Mirrors ts.hocon ``src/internal/properties/properties.ts``. Implements the whole
of ``java.util.Properties``, which is what Lightbend uses for
``include "x.properties"``: backslash continuations (S23.5), the escape set
including ``\\uXXXX`` (S23.6), ``=`` / ``:`` / whitespace separators, escaped
separators belonging to the key, and a value keeping its trailing whitespace.
S23.5 and S23.6 were out-of-scope until 2026-07-24.

Object always wins over scalar on a key conflict (S23.4, HOCON.md L1485),
enforced via key-sorted insertion so conflict direction is input-order
independent.

There is no key denylist: ``__proto__``, ``constructor`` and ``prototype`` are
ordinary keys and keep their values (F2.9). A Python ``dict`` has no prototype
to pollute, so dropping them would be data loss protecting nothing.
"""

from __future__ import annotations

from typing import Any

from ...errors import ParseError
from ...value import HoconObject, HoconScalar, HoconValue
from ..depth import MAX_PATH_SEGMENTS, too_deep

__all__ = ["parse_properties", "properties_to_hocon_value"]

_PROPS_SPACE = (" ", "\t", "\f")


def parse_properties(input_text: str) -> dict[str, Any]:
    root: dict[str, Any] = {}

    pairs: list[tuple[str, str]] = []
    for text, line_no in _logical_lines(input_text):
        raw_key, raw_value = _split_key_value(text)
        key = _unescape(raw_key, line_no)
        if key == "":
            continue
        if too_deep(key.count(".") + 1):
            # One dotted key produces one arbitrarily deep chain, so ~1 kB of
            # key text was enough to exhaust the interpreter's stack during
            # coercion — as a RecursionError, outside every error type
            # documented here. Checked in file order rather than after the sort
            # below: the sort exists to make conflict *direction* independent of
            # input order, and a key that is too deep is not a conflict.
            raise ParseError(
                f"key maps to a path {key.count('.') + 1} segments deep, over "
                f"the limit of {MAX_PATH_SEGMENTS}",
                line_no,
                1,
            )
        pairs.append((key, _unescape(raw_value, line_no)))

    # Sort by key so conflict-direction is input-order independent (S23.4).
    pairs.sort(key=lambda kv: kv[0])

    for key, value in pairs:
        _set_nested(root, key.split("."), value)

    return root


def _logical_lines(input_text: str) -> list[tuple[str, int]]:
    """Drop blank and comment lines and join backslash continuations.

    Comment status is decided per natural line before joining, so a continuation
    line that happens to start with ``#`` is value text rather than a comment.
    Each result carries the 1-based line it started on, for error messages.
    """
    natural = input_text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    out: list[tuple[str, int]] = []
    i = 0
    while i < len(natural):
        text = natural[i].lstrip(" \t\f")
        if text == "" or text.startswith("#") or text.startswith("!"):
            i += 1
            continue
        start = i + 1
        while _ends_with_continuation(text):
            text = text[:-1]
            if i + 1 >= len(natural):
                break
            i += 1
            text += natural[i].lstrip(" \t\f")
        out.append((text, start))
        i += 1
    return out


def _ends_with_continuation(line: str) -> bool:
    """An odd number of trailing backslashes leaves the last one an escape, so
    the line continues; an even number means they escape each other."""
    n = len(line) - len(line.rstrip("\\"))
    return n % 2 == 1


def _split_key_value(line: str) -> tuple[str, str]:
    """Split at the first unescaped ``=``, ``:`` or whitespace run, then skip
    whitespace around that separator. Whatever remains is the value, trailing
    whitespace included."""
    key: list[str] = []
    i = 0
    while i < len(line):
        ch = line[i]
        if ch == "\\" and i + 1 < len(line):
            key.append(ch)
            key.append(line[i + 1])
            i += 2
            continue
        if ch in ("=", ":") or ch in _PROPS_SPACE:
            break
        key.append(ch)
        i += 1
    while i < len(line) and line[i] in _PROPS_SPACE:
        i += 1
    if i < len(line) and line[i] in ("=", ":"):
        i += 1
        while i < len(line) and line[i] in _PROPS_SPACE:
            i += 1
    return "".join(key), line[i:]


def _unescape(s: str, line_no: int) -> str:
    """Apply the ``java.util.Properties`` escape rules.

    An unknown escape drops the backslash and a trailing lone backslash is
    dropped, both as Java does.
    """
    out: list[str] = []
    i = 0
    while i < len(s):
        if s[i] != "\\":
            out.append(s[i])
            i += 1
            continue
        i += 1
        if i >= len(s):
            break
        ch = s[i]
        if ch == "t":
            out.append("\t")
        elif ch == "n":
            out.append("\n")
        elif ch == "r":
            out.append("\r")
        elif ch == "f":
            out.append("\f")
        elif ch == "u":
            cp, consumed = _unicode_escape(s, i, line_no)
            out.append(cp)
            i += consumed
        else:
            out.append(ch)
        i += 1
    return "".join(out)


def _unicode_escape(s: str, i: int, line_no: int) -> tuple[str, int]:
    """Decode the ``\\uXXXX`` at ``s[i] == 'u'``, combining a surrogate pair when
    one follows. Returns the character and how many chars past ``'u'`` were used.

    A Python ``str`` can hold a lone surrogate, but encoding one to UTF-8 raises,
    so it would only defer the failure to serialization time. It is rejected here
    instead, matching go.hocon and rs.hocon; ts.hocon accepts one because its
    strings are UTF-16 like Java's (S1.2.6).
    """
    hi = _hex4(s, i + 1, line_no)
    if not 0xD800 <= hi <= 0xDFFF:
        return chr(hi), 4
    if hi > 0xDBFF:
        raise ParseError(f"\\u{hi:04X} is an unpaired low surrogate", line_no, i + 1)
    if i + 6 < len(s) and s[i + 5] == "\\" and s[i + 6] == "u":
        try:
            lo = _hex4(s, i + 7, line_no)
        except ParseError:
            lo = -1
        if 0xDC00 <= lo <= 0xDFFF:
            return chr(0x10000 + ((hi - 0xD800) << 10) + (lo - 0xDC00)), 10
    raise ParseError(f"\\u{hi:04X} is an unpaired high surrogate", line_no, i + 1)


def _hex4(s: str, start: int, line_no: int) -> int:
    digits = s[start : start + 4]
    if len(digits) < 4:
        raise ParseError("truncated \\u escape", line_no, start + 1)
    try:
        return int(digits, 16)
    except ValueError:
        raise ParseError(f'invalid \\u escape "{digits}"', line_no, start + 1) from None


def _set_nested(obj: dict[str, Any], segments: list[str], value: str) -> None:
    # F2.9 — every key is an ordinary key, `__proto__` included: a Python dict
    # has no prototype to pollute, so there is no denylist here.
    current = obj
    for seg in segments[:-1]:
        existing = current.get(seg)
        if not isinstance(existing, dict):
            current[seg] = {}
        current = current[seg]
    last = segments[-1]
    # S23.4 — object always wins over scalar: do not overwrite an object.
    if isinstance(current.get(last), dict):
        return
    current[last] = value


def properties_to_hocon_value(input_text: str) -> HoconValue:
    """Convert a ``.properties`` string to a HoconValue (object with string
    scalars). All values remain strings — no type coercion."""
    return _record_to_hocon_value(parse_properties(input_text))


def _record_to_hocon_value(obj: dict[str, Any]) -> HoconObject:
    fields: dict[str, HoconValue] = {}
    for key, val in obj.items():
        if isinstance(val, str):
            fields[key] = HoconScalar(val, "string")
        elif isinstance(val, dict):
            fields[key] = _record_to_hocon_value(val)
    return HoconObject(fields)
