"""Token and substitution-payload types. Mirrors ts.hocon ``src/internal/lexer/token.ts``.

``TokenKind`` values match the ts.hocon string literals verbatim so the parser
port reads 1:1.
"""

from __future__ import annotations

from typing import Literal

__all__ = ["Segment", "SubstPayload", "Token", "TokenKind"]

TokenKind = Literal[
    "lbrace", "rbrace",
    "lbracket", "rbracket",
    "comma", "colon", "equals", "plus_equals",
    "newline",
    "string",
    "triple_string",
    "unquoted",
    "subst",
    "eof",
]


class Segment:
    def __init__(self, text: str, line: int, col: int) -> None:
        self.text = text
        self.line = line
        self.col = col


class SubstPayload:
    def __init__(self, segments: list[Segment], optional: bool, list_suffix: bool) -> None:
        self.segments = segments
        self.optional = optional
        # True when the substitution body ends with '[]' (S13c).
        self.list_suffix = list_suffix


class Token:
    def __init__(
        self,
        kind: TokenKind,
        value: str,
        line: int,
        col: int,
        is_quoted: bool = False,
        preceding_space: bool = False,
        preceding_whitespace: str = "",
        subst: SubstPayload | None = None,
    ) -> None:
        self.kind = kind
        self.value = value
        self.line = line
        self.col = col
        self.is_quoted = is_quoted
        # True if preceded by whitespace OR a comment (concat detection: S10.5/S10.8).
        self.preceding_space = preceding_space
        # Literal preceding-whitespace chars since the previous token (path-WS
        # preservation: E13). May be "" while preceding_space is True when the
        # token is preceded only by a comment — the two answer different questions.
        self.preceding_whitespace = preceding_whitespace
        # Populated only when kind == 'subst'.
        self.subst = subst
