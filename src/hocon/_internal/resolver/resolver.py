"""The resolver's interface to the rest of the library.

Phase 1, :func:`build_tree`, turns an AST into a model tree that keeps every
assignment (includes expanded). Phase 2, :func:`resolve_tree`, resolves it and
returns public values. Between the two, a tree is opaque to callers: ``Config``
combines trees with :func:`with_fallback_tree` and looks into one only through
:func:`pending_view`, where every value that is not resolved yet is a
:class:`Placeholder`.

The algorithm is xx.hocon ``docs/resolution-model.md``; see the module
docstrings for which section lives where.
"""

from __future__ import annotations

import dataclasses

from ...value import HoconObject, HoconScalar, HoconValue
from ..parser.ast import AstNode
from .convert import (
    Placeholder,
    pending_view,
    same_marks,
    to_hocon,
    tree_from_hocon,
    val_contains_placeholders,
)
from .include_loader import IncludeLoader
from .merge import fallback
from .structure_builder import StructureBuilder
from .substitution_resolver import SubstitutionResolver
from .types import ResolveOptions
from .values import Obj, freeze, is_resolved

__all__ = [
    "Placeholder",
    "Tree",
    "build_tree",
    "contains_placeholders",
    "partial_root",
    "pending_view",
    "resolve",
    "resolve_tree",
    "resolve_with_tree",
    "same_marks",
    "strip_placeholders",
    "tree_from_value",
    "tree_key_shape",
    "val_contains_placeholders",
    "with_fallback_tree",
]

# An unresolved document, opaque outside this package.
Tree = Obj


def build_tree(ast: AstNode, opts: ResolveOptions) -> Tree:
    """Phase 1: the document's tree, substitutions unresolved, includes
    expanded (each included file is built with its own options)."""
    loader = IncludeLoader(opts)
    loader.on_build = build_tree
    tree = StructureBuilder(loader).build(ast)
    freeze(tree)  # the tree never changes again (§10.2)
    return tree


def resolve_tree(tree: Tree, opts: ResolveOptions) -> HoconValue:
    """Phase 2: the resolved document. Under ``allow_unresolved`` the result
    may hold :class:`Placeholder` values."""
    return to_hocon(SubstitutionResolver(tree, opts).resolve())


def resolve_with_tree(receiver: Tree, source: Tree, opts: ResolveOptions) -> HoconValue:
    """Phase 2 for ``resolve_with``: the receiver resolved with the source as
    its fallback for lookups (the caller keeps only the receiver's keys).
    The §10.3 weight budget counts the receiver's values plus the source's,
    each as its own root, not the merged lookup tree's."""
    merged = with_fallback_tree(receiver, source)
    return to_hocon(SubstitutionResolver(merged, opts, (receiver, source)).resolve())


def resolve(ast: AstNode, opts: ResolveOptions) -> HoconValue:
    """Both phases, as the default ``parse`` does."""
    tree = build_tree(ast, opts)
    return resolve_tree(
        tree, dataclasses.replace(opts, use_system_environment=True, allow_unresolved=False)
    )


def contains_placeholders(tree: Tree) -> bool:
    """Whether the tree still needs resolving."""
    return not is_resolved(tree)


def with_fallback_tree(receiver: Tree, fallback_tree: Tree) -> Tree:
    """§8.3 ``withFallback``: the receiver's root on top of the fallback's, by
    the §2.1 rules, with the receiver's keys first at every merged level."""
    merged = fallback([receiver], [fallback_tree], synth=False, receiver_first=True)
    top = merged[0]
    assert len(merged) == 1 and isinstance(top, Obj)
    freeze(top)
    return top


def tree_from_value(value: HoconObject) -> Tree:
    """A resolved object as a tree (for ``with_fallback`` / ``resolve_with``)."""
    return tree_from_hocon(value)


def partial_root(tree: Tree) -> HoconObject:
    """The resolved part of an unresolved tree: :func:`pending_view` without
    its placeholders (an object keeps its resolved fields)."""
    return strip_placeholders(pending_view(tree))[0]


def tree_key_shape(tree: Tree) -> HoconObject:
    """The keys a tree defines, for ``resolve_with`` (E12 decision 9). A key
    whose top assignment is an object is walked into (adjacent object
    assignments are already one merged object); any other key is a null,
    which keeps its whole resolved value. This is the shape py.hocon used
    before the window: a field whose top is an object keeps only the keys
    written in it, and a field whose top is a substitution keeps everything
    the substitution brings in."""
    fields: dict[str, HoconValue] = {}
    for k, s in tree.fields.items():
        top = s.stack[0]
        fields[k] = tree_key_shape(top) if isinstance(top, Obj) else HoconScalar("", "null")
    return HoconObject(fields)


def strip_placeholders(v: HoconObject) -> tuple[HoconObject, bool]:
    """``v`` without its unresolved values, and whether it had any. An object
    keeps its resolved fields; any other value holding a placeholder anywhere
    is dropped whole."""
    fields: dict[str, HoconValue] = {}
    had = False
    for k, val in v.fields.items():
        if isinstance(val, HoconObject):
            inner, inner_had = strip_placeholders(val)
            had = had or inner_had
            fields[k] = inner
        elif val_contains_placeholders(val):
            had = True
        else:
            fields[k] = val
    return same_marks(v, HoconObject(fields)), had
