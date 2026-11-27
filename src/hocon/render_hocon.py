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
    # ``include`` is reserved unquoted at the start of a key (S12.5/S14a) —
    # the parser (and Lightbend: "include keyword is not followed by a quoted
    # string") rejects ``include = 1``, so the key must be quoted to
    # round-trip.
    #
    # A key always takes the JSON-quoted form (E18 decision 3), never triple
    # quotes: this parser does not accept a triple-quoted key, so an LF key
    # is written as ``"a\nb"``.
    if k == "include":
        return _escape_quoted(k)
    if _SAFE_UNQUOTED_KEY_RE.fullmatch(k):
        return k
    return _escape_quoted(k)


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
    # and lossless: no embedded `"""`, no trailing `"`, and no C0 control
    # other than LF and TAB (E18 decision 5). Raw controls are valid inside
    # triple quotes (S9.1, and this lexer preserves CR verbatim per S9.2), but
    # an invisible one is ambiguous to readers, so such strings take the
    # escaped form below.
    if (
        "\n" in s
        and not _has_control_other_than_lf_tab(s)
        and '"""' not in s
        and not s.endswith('"')
    ):
        return f'"""{s}"""'
    return _escape_quoted(s)


def _escape_quoted(s: str) -> str:
    """The JSON-quoted form of *s* (E18 decision 5)."""
    out = ['"']
    for ch in s:
        short = _SHORT_ESCAPES.get(ch)
        if short is not None:
            out.append(short)
        elif ch < " ":
            # S1.2.4: a raw C0 control inside quotes is a parse error, so every
            # other one is written as \u00xx (lowercase, as Lightbend's renderer
            # does). DEL and C1 are legal and stay verbatim.
            out.append(f"\\u{ord(ch):04x}")
        else:
            out.append(ch)
    out.append('"')
    return "".join(out)


_SHORT_ESCAPES = {
    '"': '\\"',
    "\\": "\\\\",
    "\n": "\\n",
    "\r": "\\r",
    "\t": "\\t",
    "\b": "\\b",
    "\f": "\\f",
}


def _has_control_other_than_lf_tab(s: str) -> bool:
    """Whether *s* holds a C0 control (U+0000–U+001F) other than LF and TAB."""
    return any(ch < " " and ch not in "\n\t" for ch in s)
