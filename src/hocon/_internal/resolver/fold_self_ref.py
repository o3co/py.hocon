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


def prefix_self_ref_remainder(s: SubstPlaceholder, full_key: str) -> list[str] | None:
    """S13a.12: remainder segment texts when ``full_key`` is a PROPER
    segment-wise prefix of the subst's path (``foo`` ⊏ ``foo.a`` → ``["a"]``),
    else None. Boundary-safe on the dotted keys because both sides share the
    quoting of :func:`string_segments_to_key` — a literal dotted segment
    renders quoted and can never string-prefix ``foo.``."""
    texts = [seg.text for seg in s.segments]
    if not string_segments_to_key(texts).startswith(full_key + "."):
        return None
    for n in range(1, len(texts)):
        if string_segments_to_key(texts[:n]) == full_key:
            return texts[n:]
    return None


def navigate_resolver_value(
    v: ResolverValue, remainder: list[str]
) -> ResolverValue | None | _Unnavigable:
    """Structural navigation of ``remainder`` into a resolver value.

    Returns the reached node, None when a segment is missing (or the walk
    dead-ends in a scalar/array — path semantics treat both as absent), and
    the :data:`UNNAVIGABLE` sentinel when it hits a node it cannot see
    through structurally (a substitution or concat placeholder)."""
    cur: ResolverValue = v
    for seg in remainder:
        if is_subst(cur) or is_concat(cur):
            return UNNAVIGABLE
        if is_res_obj(cur):
            nxt = cur.fields.get(seg)
            if nxt is None:
                return None
            cur = nxt
            continue
        if isinstance(cur, HoconObject):
            nxt2 = cur.fields.get(seg)
            if nxt2 is None:
                return None
            cur = nxt2
            continue
        return None
    return cur


class _Unnavigable:
    """Sentinel: navigation hit a live substitution/concat mid-walk."""


UNNAVIGABLE = _Unnavigable()


def _fold_prefix_self_ref(
    s: SubstPlaceholder, replacement: ResolverValue, remainder: list[str]
) -> ResolverValue:
    """Fold one prefix self-reference against the below value. A missing path
    folds to the undefined classification (known_absent — disappears when
    optional, errors at resolve time when required); an unnavigable path
    leaves the subst unchanged for the resolve-time guard."""
    navigated = navigate_resolver_value(replacement, remainder)
    if isinstance(navigated, _Unnavigable):
        return s
    if navigated is None:
        return SubstPlaceholder(
            [Segment(seg.text, seg.line, seg.col) for seg in s.segments],
            s.optional,
            True,
            s.list_suffix,
            s.line,
            s.col,
            s.prefix_len,
        )
    return clone_resolver_value(navigated)


def _merge_res_obj_layers(base: ResObj, top: ResObj) -> ResObj:
    """Prior-layer object merge for the standalone-prefix-self-ref save case
    (S13a.12): below layer as base, navigated value on top. A local,
    bookkeeping-free merge — deliberately NOT utils.deep_merge_res_obj_into,
    which would create an import cycle and re-run prior-save logic."""
    out = ResObj()
    out.fields = dict(base.fields)
    for k, tv in top.fields.items():
        bv = out.fields.get(k)
        if bv is not None and is_res_obj(bv) and is_res_obj(tv):
            out.fields[k] = _merge_res_obj_layers(bv, tv)
        else:
            out.fields[k] = tv
    # Carry BOTH layers' bookkeeping: top's prior_values (its keys' own
    # delayed-merge chains) win per key over base's, and reset_keys union so
    # reset markers from either layer survive the splice.
    out.prior_values = {**base.prior_values, **top.prior_values}
    out.reset_keys = set(base.reset_keys) | set(top.reset_keys)
    return out


def contains_self_ref(v: ResolverValue, full_key: str) -> bool:
    return _contains_self_ref_inner(v, full_key, True)


def _contains_self_ref_inner(v: ResolverValue, full_key: str, allow_prefix: bool) -> bool:
    """``allow_prefix`` narrows the S13a.12 prefix rule to value-stack
    positions: it stays true through concat nodes and array elements (the
    value chain of the field itself) but turns false when descending into
    object interiors — a substitution nested inside an object literal that
    references a sibling branch of the same field (``a = { x = ${a.p.v} }``)
    is a lazy final-tree lookup (S13a.14), NOT a below-lookback."""
    if is_subst(v):
        return not v.known_absent and (
            subst_full_key(v) == full_key
            or (allow_prefix and prefix_self_ref_remainder(v, full_key) is not None)
        )
    if is_concat(v):
        return any(_contains_self_ref_inner(n, full_key, allow_prefix) for n in v.nodes)
    if is_res_obj(v):
        return any(_contains_self_ref_inner(f, full_key, False) for f in v.fields.values())
    if isinstance(v, HoconArray):
        return any(_contains_self_ref_inner(item, full_key, allow_prefix) for item in v.items)
    if isinstance(v, HoconObject):
        return any(_contains_self_ref_inner(f, full_key, False) for f in v.fields.values())
    return False


def fold_self_ref(
    v: ResolverValue, full_key: str, replacement: ResolverValue
) -> ResolverValue:
    return _fold_self_ref_inner(v, full_key, replacement, True)


def _fold_self_ref_inner(
    v: ResolverValue, full_key: str, replacement: ResolverValue, allow_prefix: bool
) -> ResolverValue:
    """See :func:`_contains_self_ref_inner` for the ``allow_prefix`` rule."""
    if is_subst(v):
        if subst_full_key(v) == full_key:
            return replacement
        if allow_prefix:
            remainder = prefix_self_ref_remainder(v, full_key)
            if remainder is not None:
                return _fold_prefix_self_ref(v, replacement, remainder)
        return v
    if is_concat(v):
        return ConcatPlaceholder(
            [_fold_self_ref_inner(n, full_key, replacement, allow_prefix) for n in v.nodes],
            v.line,
            v.col,
        )
    if is_res_obj(v):
        out = ResObj()
        for k, val in v.fields.items():
            out.fields[k] = _fold_self_ref_inner(val, full_key, replacement, False)
        out.prior_values = dict(v.prior_values)
        out.reset_keys = set(v.reset_keys)
        return out
    if isinstance(v, HoconArray):
        return HoconArray(
            _hv_list(
                [
                    _fold_self_ref_inner(item, full_key, replacement, allow_prefix)
                    for item in v.items
                ]
            )
        )
    if isinstance(v, HoconObject):
        return HoconObject(
            _hv_dict(
                {
                    k: _fold_self_ref_inner(val, full_key, replacement, False)
                    for k, val in v.fields.items()
                }
            )
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
    # S13a.12: a STANDALONE prefix self-ref in field-value position is a merge
    # LAYER — an object it navigates to merges over the stack below it, so the
    # saved prior keeps the below layer's other keys. An optional one whose
    # navigated path is absent vanishes transparently (the below layer itself
    # survives as the prior). Nested occurrences substitute in place via the
    # generic fold below.
    if is_subst(prior):
        remainder = prefix_self_ref_remainder(prior, full_key)
        if remainder is not None:
            navigated = navigate_resolver_value(old, remainder)
            if navigated is None and prior.optional:
                return clone_resolver_value(old)
            if (
                not isinstance(navigated, _Unnavigable)
                and navigated is not None
                and is_res_obj(navigated)
                and is_res_obj(old)
            ):
                return _merge_res_obj_layers(
                    cast("ResObj", clone_resolver_value(old)),
                    cast("ResObj", clone_resolver_value(navigated)),
                )
    return fold_self_ref(prior, full_key, old)


def _fold_optional_self_ref_absent(
    v: ResolverValue, full_key: str
) -> ResolverValue | None:
    return _fold_optional_self_ref_absent_inner(v, full_key, True)


def _fold_optional_self_ref_absent_inner(
    v: ResolverValue, full_key: str, allow_prefix: bool
) -> ResolverValue | None:
    """See :func:`_contains_self_ref_inner` for the ``allow_prefix`` rule."""
    if is_subst(v) and (
        subst_full_key(v) == full_key
        or (allow_prefix and prefix_self_ref_remainder(v, full_key) is not None)
    ):
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
            folded = _fold_optional_self_ref_absent_inner(node, full_key, allow_prefix)
            if folded is None:
                return None
            nodes.append(folded)
        return ConcatPlaceholder(nodes, v.line, v.col)
    if is_res_obj(v):
        out = ResObj()
        for key, value in v.fields.items():
            folded = _fold_optional_self_ref_absent_inner(value, full_key, False)
            if folded is None:
                return None
            out.fields[key] = folded
        out.prior_values = dict(v.prior_values)
        out.reset_keys = set(v.reset_keys)
        return out
    if isinstance(v, HoconArray):
        items: list[ResolverValue] = []
        for item in v.items:
            folded = _fold_optional_self_ref_absent_inner(item, full_key, allow_prefix)
            if folded is None:
                return None
            items.append(folded)
        return HoconArray(_hv_list(items))
    if isinstance(v, HoconObject):
        obj_fields: dict[str, ResolverValue] = {}
        for key, value in v.fields.items():
            folded = _fold_optional_self_ref_absent_inner(value, full_key, False)
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
