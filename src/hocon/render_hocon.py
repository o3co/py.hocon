"""HOCON emitter — renders a resolved value tree back to HOCON text.

Ports go.hocon ``render_hocon.go`` (``Config.RenderHOCON``, v1.11.0) per the
E18 convention (xx.hocon docs/extra-spec-conventions.md §E18). The correctness
contract is the round trip, not the byte format: parsing the output back yields
the same value tree. A scalar is quoted whenever leaving it bare would re-parse
as a different type, and left bare only when it provably cannot.

:meth:`hocon.Config.render_hocon` is the public entry point; this module holds
the tree walk (the split mirrors ``decode.py`` backing ``Config.decode``).
"""

from __future__ import annotations

import re

from .errors import ConfigError
from .value import HoconArray, HoconObject, HoconScalar, HoconValue

__all__ = ["render_root"]


def render_root(root: HoconObject) -> str:
    """Render ``root`` as a HOCON document (root fields braceless)."""
    out: list[str] = []
    _render_object_body(out, root, 0)
    return "".join(out)


def _render_object_body(out: list[str], o: HoconObject, depth: int) -> None:
    indent = "  " * depth
    for k, v in o.fields.items():
        out.append(indent)
        out.append(_render_key(k))
        if isinstance(v, HoconObject):
            out.append(" {")
            if not v.fields:
                out.append("}\n")
                continue
            out.append("\n")
            _render_object_body(out, v, depth + 1)
            out.append(indent)
            out.append("}\n")
        else:
            out.append(" = ")
            _render_value(out, v, depth)
            out.append("\n")


def _render_value(out: list[str], v: HoconValue, depth: int) -> None:
    if isinstance(v, HoconObject):
        if not v.fields:
            out.append("{}")
            return
        out.append("{\n")
        _render_object_body(out, v, depth + 1)
        out.append("  " * depth)
        out.append("}")
        return
    if isinstance(v, HoconArray):
        _render_array(out, v, depth)
        return
    if isinstance(v, HoconScalar):
        out.append(_render_scalar(v))
        return
    # Unreachable for a well-typed HoconValue, but a placeholder that leaked
    # through a cast in the resolver's partial-tree machinery lands here
    # (go.hocon's renderValue error branch).
    raise ConfigError(
        f"render_hocon: unrenderable value {type(v).__name__} (config must be resolved data)",
        "",
    )


def _render_array(out: list[str], a: HoconArray, depth: int) -> None:
    if not a.items:
        out.append("[]")
        return
    inner = "  " * (depth + 1)
    out.append("[\n")
    for e in a.items:
        out.append(inner)
        _render_value(out, e, depth + 1)
        out.append("\n")
    out.append("  " * depth)
    out.append("]")


def _render_scalar(s: HoconScalar) -> str:
    if s.value_type == "null":
        return "null"
    if s.value_type == "boolean" or s.value_type == "number":
        # raw already holds the canonical textual form; both re-parse to their
        # own type, so they are emitted bare.
        return s.raw
    return _render_string(s.raw)


# A key that is unambiguous unquoted: no dot (which would nest), no whitespace,
# no forbidden character.
_SAFE_UNQUOTED_KEY_RE = re.compile(r"[A-Za-z0-9_-]+")


def _render_key(k: str) -> str:
    if _SAFE_UNQUOTED_KEY_RE.fullmatch(k):
        return k
    return _quote_string(k)


# A string value that cannot be misread as another type: an identifier that is
# not a boolean/null keyword and not numeric. Any other string is quoted, which
# always round-trips.
_SAFE_BARE_STRING_RE = re.compile(r"[A-Za-z][A-Za-z0-9_-]*")

_STRING_KEYWORDS = frozenset({"true", "false", "null", "yes", "no", "on", "off"})


def _render_string(s: str) -> str:
    if _SAFE_BARE_STRING_RE.fullmatch(s) and s.lower() not in _STRING_KEYWORDS:
        return s
    return _quote_string(s)


def _quote_string(s: str) -> str:
    # A string containing newlines is triple-quoted when that is unambiguous
    # and lossless: no embedded `"""`, no trailing `"`, and no carriage return
    # (the parser normalizes CRLF inside triple quotes, which would drop the
    # `\r`, so those fall through to escaped double quotes below).
    if "\n" in s and "\r" not in s and '"""' not in s and not s.endswith('"'):
        return f'"""{s}"""'
    out = ['"']
    for ch in s:
        if ch == '"':
            out.append('\\"')
        elif ch == "\\":
            out.append("\\\\")
        elif ch == "\n":
            out.append("\\n")
        elif ch == "\r":
            out.append("\\r")
        elif ch == "\t":
            out.append("\\t")
        else:
            out.append(ch)
    out.append('"')
    return "".join(out)
