"""Tokenizer. Mirrors ts.hocon ``src/internal/lexer/lexer.ts``.

Python ``str`` is pre-decoded Unicode at the I/O boundary (same as JS), so the
byte-level decisions in go.hocon / rs.hocon do not apply here; S1.1 is per-impl
out of scope for the same reason as ts.hocon.
"""

from __future__ import annotations

from ...errors import ParseError
from .token import Segment, SubstPayload, Token, TokenKind

__all__ = ["tokenize"]


def _is_hocon_whitespace(ch: str) -> bool:
    """True if ``ch`` is a HOCON whitespace character per spec §Whitespace
    (HOCON.md L165-184). Canonical single-source predicate; all lexer call sites
    route through it.

    NOTE: 0x0A (LF) is included here but ``_is_hocon_newline`` takes priority in
    the main loop — the caller must check newline BEFORE whitespace. Do NOT use
    ``str.isspace()`` (includes NEL 0x0085 which HOCON does not list). Hardcode
    the set.
    """
    if ch == "":
        return False
    cp = ord(ch)
    if cp in (0x09, 0x0A, 0x0B, 0x0C, 0x0D):
        return True
    if 0x1C <= cp <= 0x1F:
        return True
    if cp in (0x20, 0xA0, 0xFEFF):
        return True
    if cp == 0x1680:
        return True
    if 0x2000 <= cp <= 0x200A:
        return True
    if cp in (0x2028, 0x2029, 0x202F, 0x205F):
        return True
    if cp == 0x3000:
        return True
    return False


def _is_hocon_newline(ch: str) -> bool:
    """True only for ASCII LF (0x0A), the sole HOCON newline character (HOCON.md
    L182-184). Zl (0x2028) / Zp (0x2029) are whitespace, NOT newlines. Must be
    checked BEFORE ``_is_hocon_whitespace`` in the main loop."""
    return ch == "\n"


_SINGLE_CHAR_TOKENS: dict[str, TokenKind] = {
    "{": "lbrace",
    "}": "rbrace",
    "[": "lbracket",
    "]": "rbracket",
    ",": "comma",
    ":": "colon",
}


def _is_decimal_digit(ch: str) -> bool:
    return "0" <= ch <= "9"


def _is_unquoted_subst_char(ch: str) -> bool:
    """True if ``ch`` is a valid unquoted char inside a ``${...}`` body."""
    if ch == "" or _is_hocon_whitespace(ch):
        return False
    if ch in '"\\':
        return False
    if ch in "{}[]":
        return False
    if ch in ":=,+#`^?!@*&$.":
        return False
    return True


def _is_unquoted_start(ch: str) -> bool:
    if ch == "" or _is_hocon_whitespace(ch):
        return False
    if ch in '{}[],:=+#"$?!@*&^\\':
        return False
    return True


def _is_unquoted_continue(ch: str, nxt: str) -> bool:
    if ch == "" or _is_hocon_whitespace(ch):
        return False
    if ch in '{}[],:=#"$?!@*&^\\':
        return False
    if ch == "+" and nxt == "=":
        return False
    if ch == "/" and nxt == "/":
        return False
    return True


class _Lexer:
    def __init__(self, input_text: str) -> None:
        if input_text and ord(input_text[0]) == 0xFEFF:
            input_text = input_text[1:]
        self.input = input_text
        self.pos = 0
        self.line = 1
        self.col = 1
        self.had_space = False
        # Accumulates literal whitespace chars consumed between tokens. Reset on
        # every token push. Comment text is NOT accumulated (E13).
        self.whitespace_buffer = ""
        self.tokens: list[Token] = []

    def tokenize(self) -> list[Token]:
        while self.pos < len(self.input):
            sl, sc = self.line, self.col
            ch = self._peek()

            # Newline — checked before whitespace (whitespace returns True for LF).
            if _is_hocon_newline(ch):
                self._advance()
                if not self.tokens or self.tokens[-1].kind != "newline":
                    self._push("newline", "\n", sl, sc)
                continue

            if _is_hocon_whitespace(ch):
                self.whitespace_buffer += ch
                self._advance()
                self.had_space = True
                continue

            # Comments — set had_space but do NOT accumulate comment text (E13).
            if ch == "/" and self._peek(1) == "/":
                while self.pos < len(self.input) and self._peek() != "\n":
                    self._advance()
                self.had_space = True
                continue
            if ch == "#":
                while self.pos < len(self.input) and self._peek() != "\n":
                    self._advance()
                self.had_space = True
                continue

            if ch in _SINGLE_CHAR_TOKENS:
                self._advance()
                self._push(_SINGLE_CHAR_TOKENS[ch], ch, sl, sc)
                continue

            if ch == "=":
                self._advance()
                self._push("equals", "=", sl, sc)
                continue
            if ch == "+" and self._peek(1) == "=":
                self._advance()
                self._advance()
                self._push("plus_equals", "+=", sl, sc)
                continue

            # Substitution ${...} or ${?...}
            if ch == "$" and self._peek(1) == "{":
                self._advance()
                self._advance()  # consume '$' and '{'
                payload = self._parse_subst_body(sl, sc)
                # Reconstruct canonical value string from segments.
                parts = []
                for s in payload.segments:
                    t = s.text
                    if (
                        t == ""
                        or "." in t
                        or " " in t
                        or "\t" in t
                        or '"' in t
                        or "\\" in t
                        or t != t.strip()
                    ):
                        escaped = t.replace("\\", "\\\\").replace('"', '\\"')
                        parts.append(f'"{escaped}"')
                    else:
                        parts.append(t)
                value = ".".join(parts)
                self._push_subst(payload, value, sl, sc)
                continue

            # Triple-quoted string
            if ch == '"' and self._peek(1) == '"' and self._peek(2) == '"':
                self._advance()
                self._advance()
                self._advance()
                value = ""
                closed = False
                while self.pos < len(self.input):
                    if self._peek() == '"':
                        quote_count = 0
                        while self.pos < len(self.input) and self._peek() == '"':
                            quote_count += 1
                            self._advance()
                        if quote_count >= 3:
                            value += '"' * (quote_count - 3)
                            closed = True
                            break
                        value += '"' * quote_count
                        continue
                    value += self._advance()
                if not closed:
                    raise ParseError("unterminated triple-quoted string", sl, sc)
                if value.startswith("\n"):
                    value = value[1:]
                self._push("triple_string", value, sl, sc, True)
                continue

            # Quoted string
            if ch == '"':
                self._advance()  # consume opening '"'
                value = self._read_quoted_string_body(sl, sc)
                self._push("string", value, sl, sc, True)
                continue

            # Unquoted string (stops at terminators and $). E8: leading '-' (not
            # followed by a digit) is admitted here; digit-leading runs are also a
            # single token; numeric coercion happens at the value layer.
            if _is_unquoted_start(ch):
                value = ""
                while self.pos < len(self.input) and _is_unquoted_continue(
                    self._peek(), self._peek(1)
                ):
                    value += self._advance()
                # ts.hocon calls value.trimEnd() here, but it is a no-op: the run
                # stops at any HOCON whitespace char, and JS's trimEnd set is a
                # subset of HOCON_WS, so the value never ends with a char trimEnd
                # would strip. Python's str.rstrip() strips a WIDER set (NEL etc.,
                # which are valid unquoted chars here), so it must NOT be used.
                self._push("unquoted", value, sl, sc)
                continue

            raise ParseError(f"unexpected character: {_json_char(ch)}", sl, sc)

        self.tokens.append(Token("eof", "", self.line, self.col))
        return self.tokens

    def _peek(self, offset: int = 0) -> str:
        idx = self.pos + offset
        return self.input[idx] if 0 <= idx < len(self.input) else ""

    def _advance(self) -> str:
        ch = self.input[self.pos] if self.pos < len(self.input) else ""
        self.pos += 1
        if ch == "\n":
            self.line += 1
            self.col = 1
        else:
            self.col += 1
        return ch

    def _push(
        self, kind: TokenKind, value: str, line: int, col: int, is_quoted: bool = False
    ) -> None:
        self.tokens.append(
            Token(
                kind,
                value,
                line,
                col,
                is_quoted,
                self.had_space,
                self.whitespace_buffer,
            )
        )
        self.had_space = False
        self.whitespace_buffer = ""

    def _push_subst(self, payload: SubstPayload, value: str, line: int, col: int) -> None:
        self.tokens.append(
            Token(
                "subst",
                value,
                line,
                col,
                False,
                self.had_space,
                self.whitespace_buffer,
                payload,
            )
        )
        self.had_space = False
        self.whitespace_buffer = ""

    def _read_quoted_string_body(self, open_line: int, open_col: int) -> str:
        """Read body of a quoted string. Opening ``"`` already consumed."""
        value = ""
        while self.pos < len(self.input) and self._peek() != '"':
            if self._peek() == "\n":
                raise ParseError("unterminated string", open_line, open_col)
            if self._peek() == "\\":
                esc_col = self.col
                self._advance()  # consume '\'
                if self.pos >= len(self.input):
                    raise ParseError("unterminated string", open_line, open_col)
                esc = self._advance()
                if esc == "n":
                    value += "\n"
                elif esc == "t":
                    value += "\t"
                elif esc == "r":
                    value += "\r"
                elif esc == '"':
                    value += '"'
                elif esc == "\\":
                    value += "\\"
                elif esc == "/":
                    value += "/"
                elif esc == "b":
                    value += "\b"
                elif esc == "f":
                    value += "\f"
                elif esc == "u":
                    if self.pos + 4 > len(self.input):
                        raise ParseError("invalid unicode escape", open_line, esc_col)
                    hex_digits = self.input[self.pos : self.pos + 4]
                    if not _is_hex4(hex_digits):
                        raise ParseError("invalid unicode escape", open_line, esc_col)
                    code = int(hex_digits, 16)
                    # Accept all \uXXXX escapes including surrogate code units
                    # (0xD800–0xDFFF): Python str, like JS/Java, can hold lone
                    # surrogates via surrogatepass. Intentional divergence from
                    # rs.hocon (Rust char cannot represent surrogates).
                    value += _from_char_code(code)
                    for _ in range(4):
                        self._advance()
                else:
                    raise ParseError(f"unknown escape sequence: \\{esc}", open_line, esc_col)
            else:
                value += self._advance()
        if self.pos >= len(self.input) or self._peek() != '"':
            raise ParseError("unterminated string", open_line, open_col)
        self._advance()  # consume closing '"'
        return value

    def _parse_subst_body(self, start_line: int, start_col: int) -> SubstPayload:
        """Parse the body of ``${...}`` (called after ``${`` consumed)."""
        optional = False
        if self._peek() == "?":
            self._advance()
            optional = True

        cur_text = ""
        cur_started = False
        cur_line = 0
        cur_col = 0

        pending_ws = ""
        segments: list[Segment] = []
        last_dot: tuple[int, int] | None = None
        list_suffix = False

        while True:
            if self.pos >= len(self.input):
                raise ParseError("unterminated substitution", start_line, start_col)
            ch = self._peek()

            if ch == "}":
                self._advance()
                pending_ws = ""
                break
            elif ch == "[":
                # S13c: `[]` suffix arm — fires at segment boundary.
                if not cur_started:
                    raise ParseError(
                        "empty segment before '[]' suffix in substitution path",
                        start_line,
                        self.col,
                    )
                # E7: only ASCII SPACE or TAB allowed between path and `[`.
                for w in pending_ws:
                    if w != " " and w != "\t":
                        raise ParseError(
                            f"only ASCII space or tab allowed between substitution path "
                            f"and '[]' suffix (got {_json_char(w)}, HOCON extra-spec E7)",
                            start_line,
                            self.col,
                        )
                segments.append(Segment(cur_text, cur_line, cur_col))
                pending_ws = ""
                list_suffix = self._parse_list_suffix(start_line)
                break
            elif ch == '"':
                q_line = start_line  # substitutions cannot span newlines
                q_col = self.col
                if cur_started:
                    cur_text += pending_ws
                pending_ws = ""
                self._advance()  # consume opening '"'
                decoded = self._read_quoted_string_body(q_line, q_col)
                cur_text += decoded
                if not cur_started:
                    cur_line = q_line
                    cur_col = q_col
                    cur_started = True
            elif _is_unquoted_subst_char(ch):
                # S8.6: a segment beginning with '-' must be followed by a digit.
                if ch == "-" and not cur_started and not _is_decimal_digit(self._peek(1)):
                    after = "EOF" if self._peek(1) == "" else _json_char(self._peek(1))
                    raise ParseError(
                        f"unquoted path segment cannot begin with '-' unless followed by "
                        f"a digit (got '-' then {after}, HOCON.md L270-276)",
                        start_line,
                        self.col,
                    )
                u_col = self.col
                if cur_started:
                    cur_text += pending_ws
                pending_ws = ""
                if not cur_started:
                    cur_line = start_line
                    cur_col = u_col
                    cur_started = True
                while self.pos < len(self.input) and _is_unquoted_subst_char(self._peek()):
                    cur_text += self._advance()
            elif ch == ".":
                dot_col = self.col
                pending_ws = ""
                if not cur_started:
                    raise ParseError("empty segment in path", start_line, dot_col)
                segments.append(Segment(cur_text, cur_line, cur_col))
                cur_text = ""
                cur_started = False
                cur_line = 0
                cur_col = 0
                last_dot = (start_line, dot_col)
                self._advance()
            elif _is_hocon_newline(ch):
                raise ParseError("unterminated substitution", start_line, start_col)
            elif _is_hocon_whitespace(ch):
                # Non-newline HOCON whitespace: buffer into pending_ws. CR is
                # whitespace, not newline — buffered here, not an error.
                pending_ws += ch
                self._advance()
            else:
                raise ParseError(
                    f"unexpected character in substitution path: {_json_char(ch)}",
                    start_line,
                    self.col,
                )

        if not list_suffix:
            if cur_started:
                segments.append(Segment(cur_text, cur_line, cur_col))
            elif len(segments) == 0:
                raise ParseError("empty substitution path", start_line, start_col)
            else:
                err_line, err_col = last_dot if last_dot is not None else (start_line, start_col)
                raise ParseError("empty segment in path", err_line, err_col)

        return SubstPayload(segments, optional, list_suffix)

    def _parse_list_suffix(self, start_line: int) -> bool:
        """Consume the literal ``[]`` suffix inside a substitution body."""
        self._advance()  # consume `[`
        after_bracket = self._peek()
        if after_bracket != "]":
            desc = "EOF" if after_bracket == "" else _json_char(after_bracket)
            raise ParseError(
                f"expected ']' after '[' in substitution list suffix (got {desc})",
                start_line,
                self.col,
            )
        self._advance()  # consume `]`
        if self._peek() != "}":
            desc = "EOF" if self._peek() == "" else _json_char(self._peek())
            raise ParseError(
                f"expected '}}' after '[]' in substitution list suffix (got {desc})",
                start_line,
                self.col,
            )
        self._advance()  # consume `}`
        return True


def _is_hex4(s: str) -> bool:
    if len(s) != 4:
        return False
    return all(c in "0123456789abcdefABCDEF" for c in s)


def _from_char_code(code: int) -> str:
    """Mirror JS ``String.fromCharCode``: build a char from a UTF-16 code unit,
    allowing lone surrogates (Python keeps them via surrogatepass)."""
    return chr(code)


def _json_char(ch: str) -> str:
    """Render a single character the way ts.hocon's ``JSON.stringify(ch)`` does
    in error messages: a double-quoted, escaped form."""
    import json

    return json.dumps(ch)


def tokenize(input_text: str) -> list[Token]:
    return _Lexer(input_text).tokenize()
