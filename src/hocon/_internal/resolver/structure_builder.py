"""Phase 1: AST -> model tree, with every assignment kept on its key's stack.

xx.hocon ``docs/resolution-model.md`` §1.4 (consolidation), §2.2 (where
:func:`.merge.fallback` is called), §2.3 (parse errors) and §7.1 (include
relativization). Nothing here resolves a substitution: the tree holds the whole
history of every field, and the resolver decides what is looked at.
"""

from __future__ import annotations

from ...errors import ParseError, ResolveError
from ..parser.ast import (
    AstArray,
    AstConcat,
    AstField,
    AstInclude,
    AstNode,
    AstObject,
    AstScalar,
    AstSubst,
)
from .include_loader import IncludeLoader
from .merge import consolidate, fallback, merge_included
from .values import Concat, Lst, Obj, Path, Scalar, Slot, Subst, Val, is_resolved

__all__ = ["StructureBuilder", "relativize"]


class StructureBuilder:
    def __init__(self, loader: IncludeLoader) -> None:
        self.loader = loader

    def build(self, ast: AstNode) -> Obj:
        """The root object of one document (an included file is built on its
        own, from its own root)."""
        if not isinstance(ast, AstObject):
            raise ResolveError("root AST must be an object", "", ast.pos.line, ast.pos.col)
        return self._body(ast, (), 0)

    # ``depth`` counts the lists the parser is inside; the value of a ``+=``
    # counts as one (§2.3, Lightbend ConfigParser.java:275 ``arrayCount``).

    def _body(self, ast: AstObject, path: Path, depth: int) -> Obj:
        obj = Obj(frozen=False)
        for fld in ast.fields:
            self._apply_field(obj, fld, path, depth)
        return obj

    def _apply_field(self, obj: Obj, field: AstField, path: Path, depth: int) -> None:
        if len(field.key) == 0:
            if isinstance(field.value, AstInclude):
                self._include(obj, field.value, path, depth)
            return
        keys = tuple(field.key)
        full = path + keys
        if field.append:
            if depth > 0:  # §2.3 [LB ConfigParser.java:262-276]
                raise ParseError(
                    "'+=' is not supported inside a list value (Lightbend: += does not "
                    "work nested inside a list)",
                    field.pos.line,
                    field.pos.col,
                )
            # §2.2: `k += v` is `k = ${?k} [v]`, with k's full path in this file.
            item = self._value(field.value, full, depth + 1)
            v: Val = Concat(
                [Subst(full, True, 0, False, field.pos.line, field.pos.col), Lst([item])],
                full,
                field.pos.line,
                field.pos.col,
            )
        else:
            v = self._value(field.value, full, depth)
        _put(obj, keys, v, path)

    def _include(self, obj: Obj, inc: AstInclude, path: Path, depth: int) -> None:
        if inc.qualifier.kind == "package":
            included = self.loader.load_package(inc.qualifier.identifier, inc.path, inc.required)
        else:
            included = self.loader.load(inc.path, inc.required, inc.qualifier.kind == "file")
        if depth > 0 and not is_resolved(included):  # §2.3 [LB ConfigParser.java:211-214]
            raise ParseError(
                "an include with substitutions is not supported inside a list value",
                inc.pos.line,
                inc.pos.col,
            )
        if path:
            included = relativize(included, path)
        merge_included(obj, included, path)

    def _value(self, ast: AstNode, path: Path, depth: int) -> Val:
        if isinstance(ast, AstScalar):
            # A parser-inserted separator is unquoted whitespace (§1.3 rule 3).
            return Scalar(ast.raw, ast.value_type, ast.quoted)
        if isinstance(ast, AstArray):
            return Lst([self._value(i, path, depth + 1) for i in ast.items])
        if isinstance(ast, AstObject):
            return self._body(ast, path, depth)
        if isinstance(ast, AstSubst):
            return Subst(
                tuple(seg.text for seg in ast.segments),
                ast.optional,
                0,
                ast.list_suffix,
                ast.pos.line,
                ast.pos.col,
            )
        if isinstance(ast, AstConcat):
            return self._concat(ast, path, depth)
        raise ResolveError("internal: an include is not a value", "", ast.pos.line, ast.pos.col)

    def _concat(self, ast: AstConcat, path: Path, depth: int) -> Val:
        """§1.4: whitespace between two pieces is kept only when neither
        neighbour is an object or a list; adjacent pieces that are neither a
        substitution nor a concatenation are joined now."""
        pieces: list[Val] = []
        nodes = ast.nodes
        for i, node in enumerate(nodes):
            if isinstance(node, AstScalar) and node.separator:
                nxt = nodes[i + 1] if i + 1 < len(nodes) else None
                if (pieces and isinstance(pieces[-1], (Obj, Lst))) or isinstance(
                    nxt, (AstObject, AstArray)
                ):
                    continue
            pieces.append(self._value(node, path, depth))
        if len(pieces) == 1:
            return pieces[0]
        joined = consolidate(pieces, at_parse=True, line=ast.pos.line, col=ast.pos.col)
        if len(joined) == 1:
            return joined[0]
        return Concat(joined, path, ast.pos.line, ast.pos.col)


def _put(obj: Obj, keys: tuple[str, ...], v: Val, path: Path) -> None:
    """§2.2: ``a.b.c = v`` is ``a = {b: {c: v}}``; a repeated key stacks the
    new value on top with :func:`fallback`."""
    k = keys[0]
    for j in range(len(keys) - 1, 0, -1):
        v = Obj({keys[j]: Slot(keys[j], [v], path + keys[: j + 1])}, frozen=False)
    existing = obj.fields.get(k)
    if existing is not None:
        existing.stack = fallback([v], existing.stack, synth=False)
    else:
        obj.fields[k] = Slot(k, [v], (*path, k))


def relativize(v: Obj, prefix: Path) -> Obj:
    """§7.1: an included file mounted at ``prefix``. Every substitution path
    gets the prefix (and remembers its length, for the original-path lookup of
    §7.2); slot and concatenation paths move under the prefix."""
    out = _relativize(v, prefix)
    assert isinstance(out, Obj)
    return out


def _relativize(v: Val, prefix: Path) -> Val:
    if isinstance(v, Subst):
        return Subst(
            prefix + v.path,
            v.optional,
            v.prefix_len + len(prefix),
            v.list_suffix,
            v.line,
            v.col,
        )
    if isinstance(v, Concat):
        return Concat([_relativize(p, prefix) for p in v.pieces], prefix + v.fpath, v.line, v.col)
    if isinstance(v, Lst):
        return Lst([_relativize(i, prefix) for i in v.items])
    if isinstance(v, Obj):
        return Obj(
            {
                k: Slot(k, [_relativize(x, prefix) for x in s.stack], prefix + s.path)
                for k, s in v.fields.items()
            },
            v.flag,
            frozen=False,
        )
    return v
