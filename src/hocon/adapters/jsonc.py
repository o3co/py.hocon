"""JSON with comments and trailing commas — the dialect VS Code and TypeScript
use for their config files — as HOCON config.

Plain JSON needs no adapter: HOCON is a JSON superset, so :func:`hocon.parse`
already accepts a ``.json`` file. This exists for the two things HOCON does not
accept, block comments and trailing commas.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .._internal.text import strip_bom
from ..config import Config
from ..value_factory import from_map
from . import AdapterError
from ._tree import common_scalar, object_root

__all__ = ["parse", "parse_file", "strip_comments"]

#: What ends a ``//`` comment. Both, not just LF: a CRLF file split across
#: readers, or a lone CR, would otherwise let the comment eat the following
#: line — and with the trailing comma behind it stripped too, the JSON stays
#: valid and a key silently disappears (spec F3.2).
#:
#: U+2028 / U+2029 are deliberately *not* here. The dialect this adapter
#: implements is the one VS Code reads, and ``node-jsonc-parser``'s
#: ``isLineBreak`` is LF and CR only, so there a comment runs through U+2028 to
#: the next real break. Ending the comment early would mean a document parses
#: one way in the editor that owns the format and another way here.
_LINE_BREAKS = ("\n", "\r")


def parse(input_text: str, origin_description: str | None = None) -> Config:
    """Read JSONC text."""
    cleaned = _strip_trailing_commas(strip_comments(strip_bom(input_text)))
    try:
        doc = json.loads(cleaned)
    except json.JSONDecodeError as e:
        raise AdapterError(f"jsonc: {e}") from None
    return from_map(object_root(doc, "jsonc", _scalar), origin_description)


def parse_file(path: str | Path) -> Config:
    """Read a JSONC file, using its path as the origin description."""
    p = Path(path)
    return parse(p.read_text(encoding="utf-8-sig"), str(p))


def _scalar(v: Any, at: str) -> Any:
    return common_scalar(v, at, "jsonc")


def strip_comments(src: str) -> str:
    """Replace ``//`` line comments and block comments with whitespace, leaving
    string literals alone. A comment becomes at least one space — never the
    empty string — so the tokens around it cannot fuse into one (``1/*x*/2``
    stays two tokens; spec F3.2). Newlines inside a removed span are kept so
    the JSON parser still reports useful line numbers, though columns after a
    comment shift by the replacement.

    A ``//`` comment ends at LF *or* CR (see :data:`_LINE_BREAKS`)."""
    out: list[str] = []
    i = 0
    while i < len(src):
        c = src[i]
        if c == '"':
            end = _end_of_string(src, i)
            out.append(src[i:end])
            i = end
        elif c == "/" and src[i : i + 2] == "//":
            while i < len(src) and src[i] not in _LINE_BREAKS:
                i += 1
            # The loop stops at the break (or EOF) and leaves it in place, so
            # the tokens are already separated: this space is for uniformity,
            # not correctness. The block-comment branch is the load-bearing one.
            out.append(" ")
        elif c == "/" and src[i : i + 2] == "/*":
            end = src.find("*/", i + 2)
            if end == -1:
                raise AdapterError("jsonc: unterminated block comment")
            out.append("\n" * src.count("\n", i, end + 2) + " ")
            i = end + 2
        else:
            out.append(c)
            i += 1
    return "".join(out)


def _end_of_string(src: str, i: int) -> int:
    """Index just past the string literal starting at ``i``."""
    j = i + 1
    while j < len(src):
        if src[j] == "\\":
            j += 2
        elif src[j] == '"':
            return j + 1
        else:
            j += 1
    raise AdapterError("jsonc: unterminated string literal")


def _strip_trailing_commas(src: str) -> str:
    """Drop a comma whose next meaningful character closes its object or array."""
    out: list[str] = []
    i = 0
    while i < len(src):
        c = src[i]
        if c == '"':
            end = _end_of_string(src, i)
            out.append(src[i:end])
            i = end
            continue
        if c == ",":
            j = i + 1
            while j < len(src) and src[j].isspace():
                j += 1
            if j < len(src) and src[j] in "}]":
                i += 1
                continue
        out.append(c)
        i += 1
    return "".join(out)
