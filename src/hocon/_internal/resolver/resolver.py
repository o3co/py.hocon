"""Resolution driver. Mirrors ts.hocon ``src/internal/resolver/resolver.ts``.

Two-phase: :func:`build_tree` (phase 1 — placeholders left in place, includes
expanded) then :func:`resolve_tree` (phase 2 — placeholders replaced). Sync path
only (py.hocon has no async parse variant).
"""

from __future__ import annotations

import dataclasses
from typing import cast

from ...value import HoconArray, HoconObject, HoconValue
from ..parser.ast import AstNode
from .structure_builder import StructureBuilder
from .substitution_resolver import SubstitutionResolver
from .types import (
    ResObj,
    ResolveOptions,
    ResolverValue,
    is_concat,
    is_res_obj,
    is_subst,
    make_res_obj,
)

__all__ = [
    "build_partial_hocon_from_res_obj",
    "build_tree",
    "contains_placeholders",
    "hocon_value_to_res_obj",
    "resolve",
    "resolve_tree",
    "val_contains_placeholders",
]


def build_tree(ast: AstNode, opts: ResolveOptions) -> ResObj:
    """Phase 1: builds a ResObj tree with substitution/concat placeholders
    unresolved. Includes are fully expanded."""
    return StructureBuilder(opts).build(ast)


def resolve_tree(tree: ResObj, opts: ResolveOptions) -> HoconValue:
    """Phase 2: replaces placeholders in a ResObj tree → fully-resolved value."""
    return SubstitutionResolver(tree, opts).resolve()


def contains_placeholders(tree: ResObj) -> bool:
    return any(val_contains_placeholders(val) for val in tree.fields.values())


def val_contains_placeholders(v: ResolverValue) -> bool:
    if is_subst(v) or is_concat(v):
        return True
    if is_res_obj(v):
        return contains_placeholders(v)
    if isinstance(v, HoconArray):
        return any(val_contains_placeholders(item) for item in v.items)
    return False


def build_partial_hocon_from_res_obj(tree: ResObj) -> HoconObject:
    """Extract resolved (non-placeholder) fields from a ResObj into a plain
    HoconValue object. Placeholder-valued fields are omitted so ``Config``
    accessors return absent → NotResolvedError."""
    fields: dict[str, HoconValue] = {}
    for k, v in tree.fields.items():
        if not is_subst(v) and not is_concat(v):
            if is_res_obj(v):
                fields[k] = build_partial_hocon_from_res_obj(v)
            elif not val_contains_placeholders(v):
                # Not a placeholder and placeholder-free → a plain HoconValue.
                fields[k] = cast("HoconValue", v)
    return HoconObject(fields)


def hocon_value_to_res_obj(value: HoconObject) -> ResObj:
    """Convert a fully-resolved HoconValue object into a ResObj (for withFallback)."""
    obj = make_res_obj()
    for k, v in value.fields.items():
        if isinstance(v, HoconObject):
            obj.fields[k] = hocon_value_to_res_obj(v)
        else:
            obj.fields[k] = v
    return obj


def resolve(ast: AstNode, opts: ResolveOptions) -> HoconValue:
    """Fused phase 1 + phase 2 (default parse behaviour)."""
    tree = build_tree(ast, opts)
    return resolve_tree(
        tree,
        dataclasses.replace(opts, use_system_environment=True, allow_unresolved=False),
    )
