"""AST construction. Mirrors ts.hocon ``src/internal/parser/parser.ts``.

Faithful port; the space-concat / path-whitespace preservation logic in
``_parse_key`` (S10.8 / E13) matches ts.hocon line-for-line.
"""

from __future__ import annotations

from ...coerce import DECIMAL_NUMBER_RE
from ...errors import ParseError
from ...value import ScalarValueType
from ..lexer.token import Token, TokenKind
from .ast import (
    AstArray,
    AstConcat,
    AstField,
    AstInclude,
    AstNode,
    AstObject,
    AstScalar,
    AstSubst,
    IncludeQualifier,
    Pos,
)

__all__ = ["parse_tokens"]

_EOF_TOKEN = Token("eof", "", 0, 0)


class _Parser:
    def __init__(self, tokens: list[Token]) -> None:
        self.tokens = tokens
        self.pos = 0

    def parse(self) -> AstNode:
        self._skip("newline")
        t = self._peek()
        if t.kind == "lbrace":
            # Braced root: parse first braced object, then continue parsing any
            # trailing content as additional root fields to merge.
            self._advance()
            first = self._parse_object(True)
            all_fields: list[AstField] = list(first.fields) if isinstance(first, AstObject) else []

            while True:
                self._skip("newline")
                if self._peek().kind == "eof":
                    break
                if self._peek().kind == "lbrace":
                    self._advance()
                    extra = self._parse_object(True)
                    if isinstance(extra, AstObject):
                        all_fields.extend(extra.fields)
                else:
                    rest = self._parse_object(False)
                    if isinstance(rest, AstObject):
                        all_fields.extend(rest.fields)
                    break

            self._skip("newline")
            remaining = self._peek()
            if remaining.kind != "eof":
                raise ParseError(
                    f"Unexpected token '{remaining.value}' after closing brace",
                    remaining.line,
                    remaining.col,
                )

            return AstObject(all_fields, first.pos)
        if t.kind == "lbracket":
            # S3.5 (HOCON.md L989-991): "both JSON and HOCON allow arrays as
            # root values in a document" — an array-root document is valid
            # syntax. The object-rooted Config API rejects it AFTER the parse,
            # at the Config boundary (parse.py) or include-load site
            # (include_loader.py), matching Lightbend's
            # Parseable.forceParsedToObject (WrongType, not a syntax error).
            # Malformed arrays and trailing content remain syntax errors. The
            # node is re-anchored at the opening `[` so the type error can
            # point at the bracket.
            self._advance()
            arr = self._parse_array()
            self._skip("newline")
            remaining = self._peek()
            if remaining.kind != "eof":
                raise ParseError(
                    f"Unexpected token '{remaining.value}' after root array",
                    remaining.line,
                    remaining.col,
                )
            return AstArray(arr.items, Pos(t.line, t.col))
        return self._parse_object(False)

    def _peek(self, offset: int = 0) -> Token:
        idx = self.pos + offset
        return self.tokens[idx] if 0 <= idx < len(self.tokens) else _EOF_TOKEN

    def _advance(self) -> Token:
        t = self.tokens[self.pos] if self.pos < len(self.tokens) else None
        if self.pos < len(self.tokens):
            self.pos += 1
        return t if t is not None else _EOF_TOKEN

    def _skip(self, *kinds: TokenKind) -> None:
        while self._peek().kind in kinds:
            self._advance()

    def _current_pos(self) -> Pos:
        t = self._peek()
        return Pos(t.line, t.col)

    def _parse_object(self, expect_closing_brace: bool) -> AstObject:
        p = self._current_pos()
        fields: list[AstField] = []

        while True:
            self._skip("newline")
            t = self._peek()
            if t.kind == "eof" or t.kind == "rbrace":
                break

            # include directive
            if t.kind == "unquoted" and t.value == "include":
                # S12.5: bare `include` followed by a value separator is a
                # key-path reservation error, not an include statement.
                nxt = self._peek(1)
                if nxt.kind in ("equals", "colon", "plus_equals", "lbrace"):
                    raise ParseError(
                        "'include' is reserved at the start of a key path expression; "
                        'use "include" (quoted) to use it as a key',
                        t.line,
                        t.col,
                    )
                self._advance()
                fields.append(self._parse_include())
                self._skip("newline")
                if self._peek().kind == "comma":
                    self._advance()
                self._skip("newline")
                continue

            # key
            key_pos = self._current_pos()
            key, first_was_quoted = self._parse_key()

            # S12.5: 'include' may not begin a key path expression (HOCON.md L570-572).
            if key and key[0] == "include" and not first_was_quoted:
                raise ParseError(
                    "'include' is reserved at the start of a key path expression; "
                    'use "include".foo (quoted) or rename the key',
                    key_pos.line,
                    key_pos.col,
                )

            # value separator (optional)
            self._skip("newline")
            append = False
            sep = self._peek()
            if sep.kind == "equals":
                self._advance()
            elif sep.kind == "plus_equals":
                self._advance()
                append = True
            elif sep.kind == "colon":
                self._advance()
            elif sep.kind == "lbrace":
                pass  # key { ... } shorthand — value parser handles it
            elif sep.kind not in ("newline", "eof"):
                raise ParseError(f"unexpected token after key: {sep.kind}", sep.line, sep.col)

            self._skip("newline")
            value = self._parse_value()
            fields.append(AstField(key, value, append, key_pos))

            self._skip("newline")
            if self._peek().kind == "comma":
                self._advance()
            self._skip("newline")

        if expect_closing_brace:
            t = self._peek()
            if t.kind != "rbrace":
                raise ParseError("expected }", t.line, t.col)
            self._advance()

        return AstObject(fields, p)

    def _parse_key(self) -> tuple[list[str], bool]:
        segments: list[str] = []
        trailing_dot = False
        first_was_quoted = False
        # S10.8 / E13: path expressions work like value concatenations. See
        # ts.hocon parser.ts parseKey for the full case table.
        space_concat = False
        post_dot_prefix = ""
        while True:
            t = self._peek()
            if t.kind == "string":
                self._advance()
                if len(segments) == 0:
                    first_was_quoted = True
                if space_concat:
                    segments[-1] = f"{segments[-1]}{t.preceding_whitespace}{t.value}"
                elif post_dot_prefix != "":
                    segments.append(f"{post_dot_prefix}{t.value}")
                    post_dot_prefix = ""
                else:
                    segments.append(t.value)  # quoted: no dot split
                trailing_dot = False
            elif t.kind == "unquoted":
                self._advance()
                # A leading '.' after existing segments (no preceding space) is
                # the separator that followed a previous quoted segment.
                if t.value.startswith(".") and len(segments) > 0 and not t.preceding_space:
                    raw = t.value[1:]
                else:
                    raw = t.value
                parts = raw.split(".")
                filtered = [s for s in parts if len(s) > 0]
                if space_concat:
                    segments[-1] = f"{segments[-1]}{t.preceding_whitespace}"
                    if raw.startswith("."):
                        segments.extend(filtered)
                    elif len(filtered) > 0:
                        head, *tail = filtered
                        segments[-1] = f"{segments[-1]}{head}"
                        segments.extend(tail)
                elif post_dot_prefix != "" and raw.startswith("."):
                    # E13 dot-WS-dot case (`a. .b = 1`): the WS becomes its own
                    # path segment between the two dot separators.
                    segments.append(post_dot_prefix)
                    post_dot_prefix = ""
                    segments.extend(filtered)
                elif post_dot_prefix != "" and len(filtered) > 0:
                    head, *tail = filtered
                    segments.append(f"{post_dot_prefix}{head}")
                    segments.extend(tail)
                    post_dot_prefix = ""
                else:
                    segments.extend(filtered)
                trailing_dot = raw.endswith(".")
            else:
                if len(segments) == 0:
                    raise ParseError(f"expected key, got {t.kind}", t.line, t.col)
                break
            space_concat = False

            if trailing_dot:
                nxt = self._peek()
                if nxt.kind in ("unquoted", "string") and len(nxt.preceding_whitespace) > 0:
                    post_dot_prefix = nxt.preceding_whitespace
                else:
                    post_dot_prefix = ""
                continue

            nxt = self._peek()
            if nxt.kind == "unquoted" and nxt.value == "." and not nxt.preceding_space:
                self._advance()  # consume the dot separator
                trailing_dot = True
                after_dot = self._peek()
                if (
                    after_dot.kind in ("unquoted", "string")
                    and len(after_dot.preceding_whitespace) > 0
                ):
                    post_dot_prefix = after_dot.preceding_whitespace
                continue
            if nxt.kind == "unquoted" and nxt.value.startswith(".") and not nxt.preceding_space:
                trailing_dot = True
                continue

            # S10.8 space-concat continuation.
            if nxt.kind in ("unquoted", "string") and nxt.preceding_space:
                space_concat = True
                continue

            break

        # E13 pw06: a key path ending with `.` creates an empty trailing
        # segment — Lightbend throws BadPath; we match.
        if trailing_dot:
            here = self._peek()
            raise ParseError(
                "path has a trailing period '.' — empty key segment not allowed "
                "(HOCON.md path rules)",
                here.line,
                here.col,
            )
        return segments, first_was_quoted

    def _parse_include(self) -> AstField:
        p = self._current_pos()
        self._skip("newline")
        t = self._peek()

        # ---- required(...) wrapper ----
        if t.kind == "unquoted" and (
            t.value == "required(" or t.value == "required" or t.value.startswith("required(")
        ):
            if t.value == "required":
                nxt = self._peek(1)
                if nxt.kind != "unquoted" or not nxt.value.startswith("("):
                    raise ParseError("include required must be followed by (", t.line, t.col)

            self._advance()

            inner_prefix = t.value[len("required(") :] if t.value.startswith("required(") else ""
            if (
                inner_prefix == "url"
                or inner_prefix.startswith("url(")
                or inner_prefix == "classpath"
                or inner_prefix.startswith("classpath(")
            ):
                raise ParseError(
                    "include url(...) and classpath(...) are not supported", t.line, t.col
                )

            next_tok = self._peek()

            if (
                inner_prefix == "package"
                or inner_prefix.startswith("package(")
                or (
                    inner_prefix == ""
                    and next_tok.kind == "unquoted"
                    and (next_tok.value == "package(" or next_tok.value.startswith("package("))
                )
            ):
                consume_package_token = inner_prefix == ""
                qualifier, path = self._parse_package_args(consume_package_token)
                return self._make_include_field(qualifier, path, True, p)

            if (
                inner_prefix == "file"
                or inner_prefix.startswith("file(")
                or (
                    inner_prefix == ""
                    and next_tok.kind == "unquoted"
                    and (next_tok.value == "file(" or next_tok.value == "file")
                )
            ):
                if inner_prefix == "":
                    self._advance()
                path = self._parse_quoted_path_skip_wrapper(t)
                return self._make_include_field(IncludeQualifier("file"), path, True, p)

            if (
                inner_prefix == ""
                and next_tok.kind == "unquoted"
                and (
                    next_tok.value == "url"
                    or next_tok.value.startswith("url(")
                    or next_tok.value == "classpath"
                    or next_tok.value.startswith("classpath(")
                )
            ):
                raise ParseError(
                    "include url(...) and classpath(...) are not supported",
                    next_tok.line,
                    next_tok.col,
                )

            if inner_prefix != "":
                if inner_prefix == ")":
                    raise ParseError(
                        "include required(...) must contain a path", t.line, t.col
                    )
                name = inner_prefix.split("(")[0].split(")")[0]
                raise ParseError(
                    f'unknown include qualifier inside required(): "{name}"', t.line, t.col
                )

            path = self._parse_quoted_path_skip_wrapper(t)
            return self._make_include_field(IncludeQualifier("bare"), path, True, p)

        # ---- bare include "path" ----
        if t.kind == "string":
            path = self._advance().value
            return self._make_include_field(IncludeQualifier("bare"), path, False, p)

        # ---- file(...) qualifier ----
        if t.kind == "unquoted" and (t.value == "file(" or t.value == "file"):
            self._advance()
            path = self._parse_quoted_path_skip_wrapper(t)
            return self._make_include_field(IncludeQualifier("file"), path, False, p)

        # ---- package(...) qualifier ----
        if t.kind == "unquoted" and (t.value == "package(" or t.value.startswith("package(")):
            qualifier, path = self._parse_package_args()
            return self._make_include_field(qualifier, path, False, p)

        if t.kind == "unquoted" and (t.value == "url" or t.value.startswith("url(")):
            raise ParseError("include url(...) is not supported", t.line, t.col)
        if t.kind == "unquoted" and (t.value == "classpath" or t.value.startswith("classpath(")):
            raise ParseError("include classpath(...) is not supported", t.line, t.col)
        raise ParseError(f"expected include path, got {t.kind}", t.line, t.col)

    def _make_include_field(
        self, qualifier: IncludeQualifier, path: str, required: bool, pos: Pos
    ) -> AstField:
        return AstField([], AstInclude(qualifier, path, required, pos), False, pos)

    def _parse_quoted_path_skip_wrapper(self, err_tok: Token) -> str:
        while self._is_include_wrapper_token(self._peek()):
            self._advance()
        if self._peek().kind != "string":
            tok = self._peek()
            if tok.kind == "eof":
                raise ParseError("expected include path", err_tok.line, err_tok.col)
            desc = f'unquoted "{tok.value}"' if tok.kind == "unquoted" else tok.kind
            raise ParseError(f"expected quoted include path, got {desc}", tok.line, tok.col)
        path = self._advance().value
        while self._peek().kind == "unquoted" and (
            self._peek().value == ")" or self._peek().value == "))"
        ):
            self._advance()
        after = self._peek()
        if after.kind not in ("newline", "rbrace", "eof", "comma"):
            desc = f'unquoted "{after.value}"' if after.kind == "unquoted" else after.kind
            raise ParseError(f"unexpected token after include path: {desc}", after.line, after.col)
        return path

    def _is_include_wrapper_token(self, tok: Token) -> bool:
        return tok.kind == "unquoted" and tok.value == "("

    def _parse_package_args(
        self, consume_package_token: bool = True
    ) -> tuple[IncludeQualifier, str]:
        pkg_tok = self._advance() if consume_package_token else self._peek()
        self._skip("newline")

        id_tok = self._peek()
        if id_tok.kind != "string":
            raise ParseError(
                "include package: expected quoted identifier as first argument",
                pkg_tok.line,
                pkg_tok.col,
            )
        identifier = self._advance().value

        self._skip("newline")
        if self._peek().kind != "comma":
            after = self._peek()
            raise ParseError(
                "include package: missing comma between identifier and file arguments"
                if after.kind == "string"
                else "include package: requires exactly two arguments (identifier, file) "
                "— one-arg form is not supported",
                pkg_tok.line,
                pkg_tok.col,
            )
        self._advance()  # consume comma
        self._skip("newline")

        file_tok = self._peek()
        if file_tok.kind != "string":
            raise ParseError(
                "include package: requires exactly two arguments (identifier, file) "
                "— one-arg form is not supported",
                pkg_tok.line,
                pkg_tok.col,
            )
        file_path = self._advance().value

        while self._peek().kind not in ("newline", "rbrace", "eof", "comma"):
            self._advance()

        return IncludeQualifier("package", identifier), file_path

    def _parse_value(self) -> AstNode:
        p = self._current_pos()
        parts: list[AstNode] = []

        while True:
            t = self._peek()
            if t.kind in ("eof", "newline", "rbrace", "rbracket", "comma"):
                break

            had_space = t.preceding_space and len(parts) > 0

            node: AstNode
            if t.kind == "lbrace":
                self._advance()
                node = self._parse_object(True)
            elif t.kind == "lbracket":
                self._advance()
                node = self._parse_array()
            elif t.kind == "subst":
                self._advance()
                if t.subst is None:
                    raise ParseError("internal: subst token missing payload", t.line, t.col)
                payload = t.subst
                node = AstSubst(
                    payload.segments, payload.optional, payload.list_suffix, Pos(t.line, t.col)
                )
            elif t.kind == "string" or t.kind == "triple_string":
                self._advance()
                node = AstScalar(t.value, "string", Pos(t.line, t.col))
            elif t.kind == "unquoted":
                self._advance()
                node = AstScalar(t.value, self._scalar_value_type(t.value), Pos(t.line, t.col))
            elif (t.kind == "colon" or t.kind == "equals") and len(parts) > 0:
                # In value concat context, colon/equals after a part are plain chars.
                self._advance()
                node = AstScalar(t.value, "string", Pos(t.line, t.col))
            else:
                break
            if had_space:
                # S10.5: inner whitespace between simple values is preserved
                # verbatim; fall back to a single space only for the comment-only
                # shape (which cannot occur mid-value-concat).
                sep = t.preceding_whitespace if len(t.preceding_whitespace) > 0 else " "
                parts.append(AstScalar(sep, "string", Pos(t.line, t.col), separator=True))
            parts.append(node)

        if len(parts) == 0:
            raise ParseError("expected value", self._peek().line, self._peek().col)
        if len(parts) == 1:
            return parts[0]
        return AstConcat(parts, p)

    def _parse_array(self) -> AstArray:
        p = self._current_pos()
        items: list[AstNode] = []

        while True:
            self._skip("newline")
            if self._peek().kind in ("rbracket", "eof"):
                break
            items.append(self._parse_value())
            self._skip("newline")
            if self._peek().kind == "comma":
                self._advance()
            self._skip("newline")

        t = self._peek()
        if t.kind != "rbracket":
            raise ParseError("expected ]", t.line, t.col)
        self._advance()
        return AstArray(items, p)

    def _scalar_value_type(self, raw: str) -> ScalarValueType:
        if raw == "true" or raw == "false":
            return "boolean"
        if raw == "null":
            return "null"
        # Number detection: first char must be 0-9 or '-' (Lightbend-aligned).
        if len(raw) > 0 and (("0" <= raw[0] <= "9") or raw[0] == "-"):
            if DECIMAL_NUMBER_RE.fullmatch(raw):
                return "number"
        return "string"


def parse_tokens(tokens: list[Token]) -> AstNode:
    return _Parser(tokens).parse()
