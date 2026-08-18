"""JSON5 (https://json5.org, spec 1.0.0) as HOCON config.

Unlike the :mod:`~hocon.adapters.jsonc` adapter — which strips comments and
hands the rest to the stdlib JSON decoder — JSON5 changes the token grammar
itself (unquoted identifier keys, single-quoted strings with line
continuations, hex integers, leading and trailing decimal points, an explicit
plus sign), so this module is a hand-rolled scanner and recursive-descent
parser. Zero dependencies, like every stdlib-only adapter in this package.

The accepted grammar is JSON5 1.0.0 as defined by the reference implementation
(the json5 npm package), the dialect owner this spec item tracks — the same
ownership rule F3.2 applies to JSONC. Where the mapping spec is stricter than
JSON5, the spec wins:

- ``Infinity`` and ``NaN`` (signed or bare) are errors, not values (spec F0.6).
- Integers — decimal or hex — must fit in int64 (spec F0.5); floats decode as
  float64-equivalent Python floats. A number written with ``.``, ``e`` or ``E``
  is a float, all other decimal forms and every hex form are integers.
- An unpaired ``\\uXXXX`` surrogate is an error, and a valid pair combines into
  the astral codepoint (spec F3.5).
- Duplicate keys follow HOCON semantics: objects merge, otherwise the later
  value wins (spec F0.7).
- The document holds exactly one value; whitespace and comments may follow it,
  anything else is an error (the strict-EOF rule F3.3 carries over from
  F3.2/JSONC).

One deliberate divergence from the JSONC adapter: JSON5's LineTerminator set
includes U+2028 and U+2029, so those *end* a ``//`` comment here, while the
dialect VS Code owns runs a comment through them (see F3.2 / F3.3 in the
format-ingestion mapping spec).

See the F3.x items in the format-ingestion mapping spec:
https://github.com/o3co/xx.hocon/blob/main/docs/format-ingestion-mapping.md
"""

from __future__ import annotations

import unicodedata
from pathlib import Path
from typing import Any

from .._internal.depth import guard_recursion
from .._internal.int64 import INT64_MAX, INT64_MIN
from .._internal.text import strip_bom
from ..config import Config
from ..value_factory import from_map
from . import AdapterError
from ._tree import common_scalar, object_root

__all__ = ["parse", "parse_file"]

#: The JSON5 LineTerminator set: LF, CR, LS, PS. This deliberately differs
#: from JSONC (F3.2), whose dialect owner ends ``//`` comments at LF/CR only —
#: the JSON5 spec includes LS and PS.
_LINE_TERMINATORS = "\n\r\u2028\u2029"

#: The explicitly named JSON5 WhiteSpace characters: TAB, VT, FF, SP, NBSP,
#: BOM. Any other Unicode Zs character is whitespace too (see
#: :func:`_is_json5_space`).
_SPACE_CHARS = "\t\v\f \u00a0\ufeff"

_HEX_DIGITS = "0123456789abcdefABCDEF"

#: ES5 SingleEscapeCharacter values the scanner maps directly. Every other
#: escaped non-digit character escapes to itself.
_SIMPLE_ESCAPES = {"n": "\n", "t": "\t", "r": "\r", "b": "\b", "f": "\f", "v": "\v"}

#: ES5 IdentifierName character classes, the key grammar the JSON5 spec
#: adopts: start = UnicodeLetter (Lu Ll Lt Lm Lo Nl) | ``$`` | ``_``; part
#: adds Mn Mc Nd Pc and ZWNJ/ZWJ.
_IDENT_START_CATEGORIES = frozenset({"Lu", "Ll", "Lt", "Lm", "Lo", "Nl"})
_IDENT_PART_CATEGORIES = _IDENT_START_CATEGORIES | {"Mn", "Mc", "Nd", "Pc"}


def parse(input_text: str, origin_description: str | None = None) -> Config:
    """Read JSON5 text. ``origin_description`` names the source in error
    messages; ``None`` leaves it to hocon's default."""
    # F0.9: a leading BOM is not data. (JSON5 additionally treats U+FEFF as
    # whitespace anywhere, which the scanner handles; stripping here keeps the
    # origin column of the first token honest.)
    text = strip_bom(input_text)
    where = _describe(origin_description)
    # Go rejects these as invalid UTF-8 the moment the scanner steps over
    # them; a Python str can hold one, so the equivalent check is explicit.
    _reject_lone_surrogates(text, where)
    parser = _Parser(text, where)
    # The parser recurses per nesting level, so the guard has to wrap it
    # rather than only the tree conversion below (see _internal.depth).
    doc = guard_recursion(
        parser.parse_document, lambda msg: AdapterError(f"json5: {msg}")
    )
    return from_map(object_root(doc, "json5", _scalar), origin_description)


def parse_file(path: str | Path) -> Config:
    """Read a JSON5 file, using its path as the origin description."""
    p = Path(path)
    return parse(p.read_text(encoding="utf-8-sig"), str(p))


def _describe(origin: str | None) -> str:
    return origin if origin else "document"


def _scalar(v: Any, at: str) -> Any:
    return common_scalar(v, at, "json5")


def _reject_lone_surrogates(text: str, where: str) -> None:
    """Refuse an unpaired surrogate code point anywhere in the source (spec
    F3.5, the same rule the jsonc adapter applies to its decoded tree).

    A Python ``str`` can hold a lone surrogate — ``surrogatepass`` and
    ``surrogateescape`` decoding both produce one — but it cannot be encoded
    as UTF-8, so the source was never a valid UTF-8 document. Go's scanner
    hits the same input as invalid UTF-8 bytes and errors wherever they hide,
    comments included; scanning up front keeps that posture.

    Escape-borne surrogates (``\\uD800`` spelled out) never reach this check:
    the string scanner handles those, pairing valid pairs (F3.5).
    """
    for ch in text:
        cp = ord(ch)
        if 0xD800 <= cp <= 0xDFFF:
            kind = "high" if cp <= 0xDBFF else "low"
            raise AdapterError(
                f"json5: {where}: \\u{cp:04X} in the source text is an unpaired "
                f"{kind} surrogate; it cannot be encoded as UTF-8 (spec F3.5)"
            )


def _is_json5_space(ch: str) -> bool:
    """The JSON5 WhiteSpace set: TAB, VT, FF, SP, NBSP, BOM, and any Unicode
    Zs character."""
    return ch in _SPACE_CHARS or unicodedata.category(ch) == "Zs"


def _is_ident_start(ch: str) -> bool:
    return ch in "$_" or unicodedata.category(ch) in _IDENT_START_CATEGORIES


def _is_ident_part(ch: str) -> bool:
    return (
        ch in "$_\u200c\u200d" or unicodedata.category(ch) in _IDENT_PART_CATEGORIES
    )


def _continues_identifier(s: str, i: int) -> bool:
    """Whether ``s`` continues with an identifier character at index ``i`` —
    used to reject tokens like ``nullx``."""
    return i < len(s) and _is_ident_part(s[i])


def _merge_objects(dst: dict[str, Any], src: dict[str, Any]) -> dict[str, Any]:
    """Merge ``src`` over ``dst`` per HOCON duplicate-key semantics (F0.7),
    returning a new dict."""
    out = dict(dst)
    for k, v in src.items():
        prev = out.get(k)
        if isinstance(prev, dict) and isinstance(v, dict):
            out[k] = _merge_objects(prev, v)
        else:
            out[k] = v
    return out


class _Parser:
    """Hand-rolled JSON5 scanner and recursive-descent parser.

    A direct port of go.hocon's ``adapters/json5`` parser; the structure is
    kept 1:1 so a fix in one implementation maps onto the other.
    """

    def __init__(self, src: str, where: str) -> None:
        self.src = src
        self.pos = 0  # code-point offset into src
        self.line = 0  # 0-based; reported 1-based
        self.line_at = 0  # offset where the current line starts
        self.where = where

    def _err(self, msg: str) -> AdapterError:
        col = self.pos - self.line_at + 1
        return AdapterError(f"json5: {self.where}: line {self.line + 1} col {col}: {msg}")

    def _advance(self, ch: str) -> None:
        self.pos += 1
        if ch in _LINE_TERMINATORS:
            # Treat CRLF as one terminator for line counting.
            if ch == "\r" and self.pos < len(self.src) and self.src[self.pos] == "\n":
                self.pos += 1
            self.line += 1
            self.line_at = self.pos

    def parse_document(self) -> Any:
        """Parse exactly one JSON5 value, allowing only whitespace and
        comments after it (the strict-EOF rule F3.3 carries over from F3.2/JSONC)."""
        self.skip_space()
        v = self.parse_value()
        self.skip_space()
        if self.pos < len(self.src):
            raise self._err("unexpected content after top-level value")
        return v

    def skip_space(self) -> None:
        """Consume whitespace, line terminators, and both comment forms."""
        src = self.src
        while self.pos < len(src):
            ch = src[self.pos]
            if _is_json5_space(ch) or ch in _LINE_TERMINATORS:
                self._advance(ch)
            elif ch == "/" and src[self.pos + 1 : self.pos + 2] == "/":
                self.pos += 2
                while self.pos < len(src) and src[self.pos] not in _LINE_TERMINATORS:
                    self.pos += 1
            elif ch == "/" and src[self.pos + 1 : self.pos + 2] == "*":
                self.pos += 2
                closed = False
                while self.pos < len(src):
                    if src[self.pos] == "*" and src[self.pos + 1 : self.pos + 2] == "/":
                        self.pos += 2
                        closed = True
                        break
                    self._advance(src[self.pos])
                if not closed:
                    raise self._err("unterminated /* comment")
            else:
                return

    def parse_value(self) -> Any:
        if self.pos >= len(self.src):
            raise self._err("unexpected end of input, expected a value")
        ch = self.src[self.pos]
        if ch == "{":
            return self.parse_object()
        if ch == "[":
            return self.parse_array()
        if ch in "\"'":
            return self.parse_string(ch)
        if ch in "+-." or "0" <= ch <= "9":
            return self.parse_number()
        return self.parse_keyword()

    def parse_keyword(self) -> Any:
        """Handle true/false/null and reject Infinity/NaN by name so the
        error explains itself (spec F0.6)."""
        rest = self.src[self.pos :]
        for kw, val in (("true", True), ("false", False), ("null", None)):
            if rest.startswith(kw) and not _continues_identifier(rest, len(kw)):
                self.pos += len(kw)
                return val
        for kw in ("Infinity", "NaN"):
            if rest.startswith(kw) and not _continues_identifier(rest, len(kw)):
                raise self._err(
                    f"{kw} is not representable in the HOCON number model (spec F0.6)"
                )
        raise self._err(f"unexpected character {rest[0]!r}")

    # -----------------------------------------------------------------------
    # Objects and arrays
    # -----------------------------------------------------------------------

    def parse_object(self) -> dict[str, Any]:
        self.pos += 1  # '{'
        obj: dict[str, Any] = {}
        while True:
            self.skip_space()
            if self.pos >= len(self.src):
                raise self._err("unterminated object, expected '}'")
            if self.src[self.pos] == "}":
                self.pos += 1
                return obj
            key = self.parse_member_name()
            self.skip_space()
            if self.pos >= len(self.src) or self.src[self.pos] != ":":
                raise self._err(f"expected ':' after object key {key!r}")
            self.pos += 1
            self.skip_space()
            val = self.parse_value()
            # F0.7: duplicate keys follow HOCON semantics — two objects merge,
            # any other combination is last-wins.
            prev = obj.get(key)
            if isinstance(prev, dict) and isinstance(val, dict):
                val = _merge_objects(prev, val)
            obj[key] = val
            self.skip_space()
            if self.pos >= len(self.src):
                raise self._err("unterminated object, expected ',' or '}'")
            ch = self.src[self.pos]
            if ch == ",":
                self.pos += 1  # trailing comma before '}' is legal; loop handles it
            elif ch == "}":
                self.pos += 1
                return obj
            else:
                raise self._err("expected ',' or '}' in object")

    def parse_array(self) -> list[Any]:
        self.pos += 1  # '['
        arr: list[Any] = []
        while True:
            self.skip_space()
            if self.pos >= len(self.src):
                raise self._err("unterminated array, expected ']'")
            if self.src[self.pos] == "]":
                self.pos += 1
                return arr
            arr.append(self.parse_value())
            self.skip_space()
            if self.pos >= len(self.src):
                raise self._err("unterminated array, expected ',' or ']'")
            ch = self.src[self.pos]
            if ch == ",":
                self.pos += 1  # trailing comma before ']' is legal; loop handles it
            elif ch == "]":
                self.pos += 1
                return arr
            else:
                raise self._err("expected ',' or ']' in array")

    # -----------------------------------------------------------------------
    # Member names (quoted or ES5 IdentifierName)
    # -----------------------------------------------------------------------

    def parse_member_name(self) -> str:
        ch = self.src[self.pos]
        if ch in "\"'":
            return self.parse_string(ch)
        return self.parse_identifier()

    def parse_identifier(self) -> str:
        """Scan an ES5 IdentifierName, honouring ``\\uXXXX`` escapes in the
        name (the escaped codepoint must itself be a legal identifier
        character for its position, per ES5 — ``1`` cannot start a key)."""
        out: list[str] = []
        first = True
        while self.pos < len(self.src):
            ch = self.src[self.pos]
            escaped = False
            if ch == "\\":
                if self.src[self.pos + 1 : self.pos + 2] != "u":
                    raise self._err("only \\uXXXX escapes are allowed in identifiers")
                self.pos += 2
                ch = self._read_hex4()
                escaped = True
            legal = _is_ident_start(ch) if first else _is_ident_part(ch)
            if not legal:
                if escaped:
                    raise self._err(
                        f"escape \\u{ord(ch):04X} is not a valid identifier character here"
                    )
                if first:
                    raise self._err(f"expected an object key, got {ch!r}")
                break
            out.append(ch)
            if not escaped:
                self.pos += 1
            first = False
        if not out:
            raise self._err("expected an object key")
        return "".join(out)

    def _read_hex4(self) -> str:
        """Read exactly four hex digits at ``pos`` and return the character.

        The digit check is explicit because ``int(s, 16)`` tolerates spellings
        the grammar does not — surrounding whitespace, an interior ``_``, a
        leading sign.
        """
        quad = self.src[self.pos : self.pos + 4]
        if len(quad) < 4:
            raise self._err("truncated \\u escape")
        if any(c not in _HEX_DIGITS for c in quad):
            raise self._err(f'invalid \\u escape "\\u{quad}"')
        self.pos += 4
        return chr(int(quad, 16))

    # -----------------------------------------------------------------------
    # Strings
    # -----------------------------------------------------------------------

    def parse_string(self, quote: str) -> str:
        """Scan a single- or double-quoted JSON5 string. ``quote`` is the
        opening quote character. JSON5 differences from JSON: either quote
        character, ``\\xHH`` escapes, ``\\v``, ``\\0``, line continuations
        (backslash before a line terminator, including CRLF as one), any other
        non-digit character escaping to itself, and unescaped LS/PS allowed
        inside the string."""
        self.pos += 1  # opening quote
        out: list[str] = []
        while True:
            if self.pos >= len(self.src):
                raise self._err("unterminated string")
            ch = self.src[self.pos]
            if ch == quote:
                self.pos += 1
                return "".join(out)
            if ch in "\n\r":
                raise self._err("unescaped line terminator in string")
            if ch == "\\":
                self.pos += 1
                self._read_escape(out)
            else:
                # LS/PS are legal unescaped inside JSON5 strings.
                out.append(ch)
                self._advance(ch)

    def _read_escape(self, out: list[str]) -> None:
        """Consume one escape sequence (the backslash is already consumed)
        and append its value to ``out``."""
        if self.pos >= len(self.src):
            raise self._err("unterminated escape sequence")
        ch = self.src[self.pos]
        # Line continuation: backslash before a line terminator joins the
        # lines, contributing nothing. CRLF counts as one terminator.
        if ch in _LINE_TERMINATORS:
            self._advance(ch)
            return
        simple = _SIMPLE_ESCAPES.get(ch)
        if simple is not None:
            self.pos += 1
            out.append(simple)
            return
        if ch == "0":
            # \0 is NUL unless followed by a decimal digit (octal escapes are
            # not part of JSON5).
            if "0" <= self.src[self.pos + 1 : self.pos + 2] <= "9":
                raise self._err("octal escape sequences are not allowed")
            self.pos += 1
            out.append("\x00")
            return
        if "1" <= ch <= "9":
            raise self._err(f"escape \\{ch} is not allowed (digits cannot be escaped)")
        if ch == "x":
            self.pos += 1
            pair = self.src[self.pos : self.pos + 2]
            if len(pair) < 2:
                raise self._err("truncated \\x escape")
            if any(c not in _HEX_DIGITS for c in pair):
                raise self._err("invalid \\x escape")
            self.pos += 2
            out.append(chr(int(pair, 16)))
            return
        if ch == "u":
            self.pos += 1
            cp = ord(self._read_hex4())
            # F3.5: a lone surrogate is an error; a valid pair combines.
            if 0xD800 <= cp <= 0xDFFF:
                if self.src[self.pos : self.pos + 2] == "\\u":
                    self.pos += 2
                    lo = ord(self._read_hex4())
                    if 0xD800 <= cp <= 0xDBFF and 0xDC00 <= lo <= 0xDFFF:
                        out.append(chr(0x10000 + ((cp - 0xD800) << 10) + (lo - 0xDC00)))
                        return
                raise self._err(f"unpaired \\u{cp:04X} surrogate (spec F3.5)")
            out.append(chr(cp))
            return
        # Any other character escapes to itself (JSON5 SingleEscapeCharacter
        # and NonEscapeCharacter collapse to this rule).
        out.append(ch)
        self._advance(ch)

    # -----------------------------------------------------------------------
    # Numbers
    # -----------------------------------------------------------------------

    def parse_number(self) -> int | float:
        """Scan a JSON5 numeric literal: optional sign, then a hex integer or
        a decimal with optional leading/trailing point and exponent. Signed
        Infinity/NaN are routed to the F0.6 error here."""
        src = self.src
        start = self.pos
        neg = False
        if src[self.pos] in "+-":
            neg = src[self.pos] == "-"
            self.pos += 1
        rest = src[self.pos :]
        for kw in ("Infinity", "NaN"):
            if rest.startswith(kw) and not _continues_identifier(rest, len(kw)):
                raise self._err(
                    f"{kw} is not representable in the HOCON number model (spec F0.6)"
                )
        if rest[:2] in ("0x", "0X"):
            self.pos += 2
            ds = self.pos
            while self.pos < len(src) and src[self.pos] in _HEX_DIGITS:
                self.pos += 1
            if self.pos == ds:
                raise self._err("hex literal needs at least one digit")
            # F0.5 — integers are int64. Python's int is unbounded, so the
            # bound is stated rather than inherited from the type.
            mag = int(src[ds : self.pos], 16)
            value = -mag if neg else mag
            if not INT64_MIN <= value <= INT64_MAX:
                raise self._err(
                    f"integer {src[start : self.pos]} does not fit in int64 (spec F0.5)"
                )
            return value

        saw_digit = saw_dot = saw_exp = False
        while self.pos < len(src):
            c = src[self.pos]
            if "0" <= c <= "9":
                saw_digit = True
            elif c == "." and not saw_dot and not saw_exp:
                saw_dot = True
            elif c in "eE" and saw_digit and not saw_exp:
                saw_exp = True
                if self.pos + 1 < len(src) and src[self.pos + 1] in "+-":
                    self.pos += 1
            else:
                break
            self.pos += 1
        text = src[start : self.pos]
        if not saw_digit:
            raise self._err(f"malformed number {text!r}")
        # F0.5: '.', 'e', 'E' make a float; everything else is an int64 or an
        # error. Python's float() and int() both accept a leading '+'.
        if saw_dot or saw_exp:
            try:
                return float(text)
            except ValueError:
                raise self._err(f"malformed number {text!r}") from None
        value = int(text)
        if not INT64_MIN <= value <= INT64_MAX:
            raise self._err(f"integer {text} does not fit in int64 (spec F0.5)")
        return value
