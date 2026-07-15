"""Helpers for chained / value-interior self-referential-substitution support.

Mirrors ts.hocon ``src/internal/resolver/fold-self-ref.ts`` (itself a port of
go.hocon ``foldselfref.go`` and rs.hocon ``fold_self_ref.rs``). Folds
occurrences of ``${key}`` inside a value about to be saved as ``prior_values[key]``
against the OLD prior, so by induction every saved prior is self-ref-free — the
fix for the N≥3 self-append chain overflow (#118 / #120).

For the ts-known-violation item S13a.3, the reference behaviour is rs.hocon's;
this port follows ts.hocon structurally, matching rs where they agree.
"""

from __future__ import annotations

import re
from typing import cast

from ...value import HoconArray, HoconObject, HoconValue
from ..lexer.token import Segment
from .types import (
    ConcatPlaceholder,
    ResObj,
    ResolverValue,
    SubstPlaceholder,
    is_concat,
    is_res_obj,
    is_subst,
)

__all__ = [
    "clone_resolver_value",
    "contains_self_ref",
    "contains_subst_by_path",
    "fold_known_absent_self_ref",
    "fold_nested_self_refs",
    "fold_or_skip_prior",
    "fold_self_ref",
    "string_segments_to_key",
    "subst_full_key",
]

_NON_BARE_KEY = re.compile(r"[^a-zA-Z0-9\-_]")


def _hv_list(items: list[ResolverValue]) -> list[HoconValue]:
    # Resolver containers transiently hold placeholders during folding; ts.hocon
    # casts these ``as HoconValue``. The public array/object contract remains
    # HoconValue-only, so the cast is contained to these builder sites.
    return cast("list[HoconValue]", items)


def _hv_dict(fields: dict[str, ResolverValue]) -> dict[str, HoconValue]:
    return cast("dict[str, HoconValue]", fields)


def string_segments_to_key(segments: list[str]) -> str:
    parts = []
    for t in segments:
        if t == "" or _NON_BARE_KEY.search(t):
            parts.append('"' + t.replace("\\", "\\\\").replace('"', '\\"') + '"')
        else:
            parts.append(t)
    return ".".join(parts)


def subst_full_key(s: SubstPlaceholder) -> str:
    return string_segments_to_key([seg.text for seg in s.segments])


def contains_self_ref(v: ResolverValue, full_key: str) -> bool:
    if is_subst(v):
        return not v.known_absent and subst_full_key(v) == full_key
    if is_concat(v):
        return any(contains_self_ref(n, full_key) for n in v.nodes)
    if is_res_obj(v):
        return any(contains_self_ref(f, full_key) for f in v.fields.values())
    if isinstance(v, HoconArray):
        return any(contains_self_ref(item, full_key) for item in v.items)
    if isinstance(v, HoconObject):
        return any(contains_self_ref(f, full_key) for f in v.fields.values())
    return False


def fold_self_ref(
    v: ResolverValue, full_key: str, replacement: ResolverValue
) -> ResolverValue:
    if is_subst(v):
        return replacement if subst_full_key(v) == full_key else v
    if is_concat(v):
        return ConcatPlaceholder(
            [fold_self_ref(n, full_key, replacement) for n in v.nodes], v.line, v.col
        )
    if is_res_obj(v):
        out = ResObj()
        for k, val in v.fields.items():
            out.fields[k] = fold_self_ref(val, full_key, replacement)
        out.prior_values = dict(v.prior_values)
        out.reset_keys = set(v.reset_keys)
        return out
    if isinstance(v, HoconArray):
        return HoconArray(
            _hv_list([fold_self_ref(item, full_key, replacement) for item in v.items])
        )
    if isinstance(v, HoconObject):
        return HoconObject(
            _hv_dict({k: fold_self_ref(val, full_key, replacement) for k, val in v.fields.items()})
        )
    return v


def fold_known_absent_self_ref(
    v: ResolverValue, full_key: str, replacement: ResolverValue
) -> ResolverValue:
    if is_subst(v):
        return replacement if (v.known_absent and subst_full_key(v) == full_key) else v
    if is_concat(v):
        return ConcatPlaceholder(
            [fold_known_absent_self_ref(n, full_key, replacement) for n in v.nodes],
            v.line,
            v.col,
        )
    if is_res_obj(v):
        out = ResObj()
        for k, val in v.fields.items():
            out.fields[k] = fold_known_absent_self_ref(val, full_key, replacement)
        out.prior_values = dict(v.prior_values)
        out.reset_keys = set(v.reset_keys)
        return out
    if isinstance(v, HoconArray):
        return HoconArray(
            _hv_list(
                [fold_known_absent_self_ref(item, full_key, replacement) for item in v.items]
            )
        )
    if isinstance(v, HoconObject):
        return HoconObject(
            _hv_dict(
                {
                    k: fold_known_absent_self_ref(val, full_key, replacement)
                    for k, val in v.fields.items()
                }
            )
        )
    return v


def fold_or_skip_prior(
    prior: ResolverValue, full_key: str, old: ResolverValue | None
) -> ResolverValue | None:
    """Three-way decision at a prior-save site (see ts.hocon fold-self-ref.ts)."""
    if not contains_self_ref(prior, full_key):
        return clone_resolver_value(prior)
    if old is None:
        return _fold_optional_self_ref_absent(prior, full_key)
    return fold_self_ref(prior, full_key, old)


def _fold_optional_self_ref_absent(
    v: ResolverValue, full_key: str
) -> ResolverValue | None:
    if is_subst(v) and subst_full_key(v) == full_key:
        if not v.optional:
            return None
        return SubstPlaceholder(
            [Segment(seg.text, seg.line, seg.col) for seg in v.segments],
            v.optional,
            True,
            v.list_suffix,
            v.line,
            v.col,
            v.prefix_len,
        )
    if is_concat(v):
        nodes: list[ResolverValue] = []
        for node in v.nodes:
            folded = _fold_optional_self_ref_absent(node, full_key)
            if folded is None:
                return None
            nodes.append(folded)
        return ConcatPlaceholder(nodes, v.line, v.col)
    if is_res_obj(v):
        out = ResObj()
        for key, value in v.fields.items():
            folded = _fold_optional_self_ref_absent(value, full_key)
            if folded is None:
                return None
            out.fields[key] = folded
        out.prior_values = dict(v.prior_values)
        out.reset_keys = set(v.reset_keys)
        return out
    if isinstance(v, HoconArray):
        items: list[ResolverValue] = []
        for item in v.items:
            folded = _fold_optional_self_ref_absent(item, full_key)
            if folded is None:
                return None
            items.append(folded)
        return HoconArray(_hv_list(items))
    if isinstance(v, HoconObject):
        obj_fields: dict[str, ResolverValue] = {}
        for key, value in v.fields.items():
            folded = _fold_optional_self_ref_absent(value, full_key)
            if folded is None:
                return None
            obj_fields[key] = folded
        return HoconObject(_hv_dict(obj_fields))
    return clone_resolver_value(v)


def clone_resolver_value(v: ResolverValue) -> ResolverValue:
    """Deep-clone a ResolverValue. Scalars share their reference (immutable and
    identity-observable via ``separator_values``)."""
    if is_subst(v):
        return SubstPlaceholder(
            [Segment(seg.text, seg.line, seg.col) for seg in v.segments],
            v.optional,
            v.known_absent,
            v.list_suffix,
            v.line,
            v.col,
            v.prefix_len,
        )
    if is_concat(v):
        return ConcatPlaceholder([clone_resolver_value(n) for n in v.nodes], v.line, v.col)
    if is_res_obj(v):
        out = ResObj()
        for k, val in v.fields.items():
            out.fields[k] = clone_resolver_value(val)
        for k, val in v.prior_values.items():
            out.prior_values[k] = clone_resolver_value(val)
        out.reset_keys = set(v.reset_keys)
        return out
    if isinstance(v, HoconArray):
        return HoconArray(_hv_list([clone_resolver_value(item) for item in v.items]))
    if isinstance(v, HoconObject):
        return HoconObject(
            _hv_dict({k: clone_resolver_value(val) for k, val in v.fields.items()})
        )
    return v


def fold_nested_self_refs(v: ResolverValue, path_prefix: list[str]) -> ResolverValue:
    """Recursively fold nested self-refs inside a ResObj tree using each enclosing
    ResObj's ``prior_values`` as the substitution target (multi-segment
    object-merge case, #120-class)."""
    if not is_res_obj(v):
        return v
    out = ResObj()
    for k, field_val in v.fields.items():
        child_path = [*path_prefix, k]
        full_key = string_segments_to_key(child_path)
        folded = fold_nested_self_refs(field_val, child_path)
        final_val = folded
        if contains_self_ref(folded, full_key):
            leaf_prior = v.prior_values.get(k)
            if leaf_prior is not None:
                leaf_prior_folded = fold_nested_self_refs(leaf_prior, child_path)
                final_val = fold_self_ref(folded, full_key, leaf_prior_folded)
        out.fields[k] = final_val
    out.prior_values = dict(v.prior_values)
    out.reset_keys = set(v.reset_keys)
    return out


def contains_subst_by_path(v: ResolverValue, target: list[Segment]) -> bool:
    if is_subst(v):
        return not v.known_absent and _segments_text_equal(v.segments, target)
    if is_concat(v):
        return any(contains_subst_by_path(n, target) for n in v.nodes)
    if is_res_obj(v):
        return any(contains_subst_by_path(f, target) for f in v.fields.values())
    if isinstance(v, HoconArray):
        return any(contains_subst_by_path(item, target) for item in v.items)
    if isinstance(v, HoconObject):
        return any(contains_subst_by_path(f, target) for f in v.fields.values())
    return False


def _segments_text_equal(a: list[Segment], b: list[Segment]) -> bool:
    if len(a) != len(b):
        return False
    return all(a[i].text == b[i].text for i in range(len(a)))
