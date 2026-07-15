"""AST node types. Mirrors ts.hocon ``src/internal/parser/ast.ts``.

Discriminated unions become plain classes narrowed by ``isinstance``. Field
names match ts.hocon (``value_type`` for the scalar's ``valueType``, etc.).
"""

from __future__ import annotations

from typing import Literal

from ...value import ScalarValueType
from ..lexer.token import Segment

__all__ = [
    "AstArray",
    "AstConcat",
    "AstField",
    "AstInclude",
    "AstNode",
    "AstObject",
    "AstScalar",
    "AstSubst",
    "IncludeQualifier",
    "Pos",
]


class Pos:
    def __init__(self, line: int, col: int, file: str | None = None) -> None:
        self.line = line
        self.col = col
        self.file = file


class IncludeQualifier:
    """Discriminated include qualifier.

    - ``bare``: ``include "path"`` — resolves relative to the including file's dir
    - ``file``: ``include file("path")`` — resolves relative to CWD (or absolute)
    - ``package``: ``include package("id", "file")`` — resolves via module lookup
    """

    def __init__(self, kind: Literal["bare", "file", "package"], identifier: str = "") -> None:
        self.kind = kind
        self.identifier = identifier


class AstObject:
    kind: Literal["object"] = "object"

    def __init__(self, fields: list[AstField], pos: Pos) -> None:
        self.fields = fields
        self.pos = pos


class AstArray:
    kind: Literal["array"] = "array"

    def __init__(self, items: list[AstNode], pos: Pos) -> None:
        self.items = items
        self.pos = pos


class AstScalar:
    kind: Literal["scalar"] = "scalar"

    def __init__(
        self, raw: str, value_type: ScalarValueType, pos: Pos, separator: bool = False
    ) -> None:
        self.raw = raw
        self.value_type = value_type
        self.pos = pos
        # Mirrors ts.hocon `_separator` — a parser-inserted whitespace piece.
        self.separator = separator


class AstConcat:
    kind: Literal["concat"] = "concat"

    def __init__(self, nodes: list[AstNode], pos: Pos) -> None:
        self.nodes = nodes
        self.pos = pos


class AstSubst:
    kind: Literal["subst"] = "subst"

    def __init__(
        self, segments: list[Segment], optional: bool, list_suffix: bool, pos: Pos
    ) -> None:
        self.segments = segments
        self.optional = optional
        self.list_suffix = list_suffix
        self.pos = pos


class AstInclude:
    kind: Literal["include"] = "include"

    def __init__(
        self, qualifier: IncludeQualifier, path: str, required: bool, pos: Pos
    ) -> None:
        self.qualifier = qualifier
        self.path = path
        self.required = required
        self.pos = pos


AstNode = AstObject | AstArray | AstScalar | AstConcat | AstSubst | AstInclude


class AstField:
    """``key`` empty ⇒ include directive (``value`` is an :class:`AstInclude`)."""

    def __init__(self, key: list[str], value: AstNode, append: bool, pos: Pos) -> None:
        # Each element is dot-split already; quoted keys are not dot-split.
        self.key = key
        self.value = value
        self.append = append  # True for the += operator
        self.pos = pos
