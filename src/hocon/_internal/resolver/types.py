"""Resolver-shared types: placeholder nodes, ``ResObj``, ``ResolveOptions``,
and the unresolved-tree merge helpers.

Mirrors ts.hocon ``src/internal/resolver/types.ts``. ``ResolverValue`` is the
union carried through phase 1 (build) before phase 2 (resolve) replaces the
placeholders.
"""

from __future__ import annotations

import weakref
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TypeGuard

from ...value import HoconScalar, HoconValue
from ..lexer.token import Segment

__all__ = [
    "ConcatPlaceholder",
    "PackageResolver",
    "ResObj",
    "ResolveOptions",
    "ResolverValue",
    "SubstPlaceholder",
    "get_prior",
    "is_concat",
    "is_res_obj",
    "is_subst",
    "make_res_obj",
    "merge_unresolved",
    "separator_values",
    "set_prior",
]


class SubstPlaceholder:
    def __init__(
        self,
        segments: list[Segment],
        optional: bool,
        known_absent: bool,
        list_suffix: bool,
        line: int,
        col: int,
        prefix_len: int,
    ) -> None:
        self.segments = segments
        self.optional = optional
        # Internal sentinel for a folded optional self-ref with no prior value.
        self.known_absent = known_absent
        self.list_suffix = list_suffix
        self.line = line
        self.col = col
        # 0 for normal, >0 for relativized (number of prefix segments).
        self.prefix_len = prefix_len


class ConcatPlaceholder:
    def __init__(self, nodes: list[ResolverValue], line: int, col: int) -> None:
        self.nodes = nodes
        self.line = line
        self.col = col


class ResObj:
    def __init__(self) -> None:
        self.fields: dict[str, ResolverValue] = {}
        self.prior_values: dict[str, ResolverValue] = {}
        # Keys whose net value was established by an explicit non-self-referential
        # assignment (a reset rather than a += / self-ref append). See go.hocon#134.
        self.reset_keys: set[str] = set()


ResolverValue = HoconValue | SubstPlaceholder | ConcatPlaceholder | ResObj

PackageResolver = Callable[[str, str, str | None, str | None], str]


def _no_files(_path: str) -> str:
    raise RuntimeError("no file reader configured")


@dataclass
class ResolveOptions:
    env: dict[str, str] = field(default_factory=dict)
    base_dir: str | None = None
    read_file_sync: Callable[[str], str] = _no_files
    include_stack: list[str] = field(default_factory=list)
    # Override the starting dir(s) for the default package resolver.
    resolve_from: str | list[str] | None = None
    package_resolver: PackageResolver | None = None
    # When False, env var lookups in SubstitutionResolver are suppressed.
    use_system_environment: bool | None = None
    # When True, leaves unresolved non-optional placeholders in place.
    allow_unresolved: bool | None = None
    # Human-readable origin for error messages.
    origin_description: str | None = None


# Track parser-inserted separator whitespace values without leaking a flag into
# the public HoconValue type. WeakSet keys on identity, so values GC normally.
separator_values: weakref.WeakSet[HoconScalar] = weakref.WeakSet()


def is_subst(v: ResolverValue) -> TypeGuard[SubstPlaceholder]:
    return isinstance(v, SubstPlaceholder)


def is_concat(v: ResolverValue) -> TypeGuard[ConcatPlaceholder]:
    return isinstance(v, ConcatPlaceholder)


def is_res_obj(v: ResolverValue) -> TypeGuard[ResObj]:
    return isinstance(v, ResObj)


def make_res_obj() -> ResObj:
    return ResObj()


def set_prior(o: ResObj, key: str, v: ResolverValue) -> None:
    o.prior_values[key] = v


def get_prior(o: ResObj, key: str) -> ResolverValue | None:
    return o.prior_values.get(key)


def merge_unresolved(receiver: ResObj, fallback: ResObj) -> ResObj:
    """E12 withFallback merge of two unresolved trees. Receiver's keys win; on a
    non-object collision the fallback's value is recorded as a prior on the
    result for cross-layer self-reference lookback in phase 2."""
    # Function-local import breaks the types ↔ fold_self_ref cycle (both only
    # touch the other's bindings inside function bodies, as ts.hocon notes).
    from .fold_self_ref import fold_or_skip_prior

    result = make_res_obj()
    for k, v in fallback.fields.items():
        result.fields[k] = v
    for k, v in fallback.prior_values.items():
        result.prior_values[k] = v
    for k, rv in receiver.fields.items():
        existing = result.fields.get(k)
        if existing is not None:
            rec_prior = receiver.prior_values.get(k)
            if rec_prior is not None and not is_res_obj(rec_prior):
                result.fields[k] = rv
                continue
            if is_res_obj(rv) and is_res_obj(existing):
                result.fields[k] = merge_unresolved(rv, existing)
                continue
            # Non-object collision: receiver wins; capture the fallback's value
            # (existing) as prior, folded self-ref-free first (go.hocon#134).
            folded_prior = fold_or_skip_prior(existing, k, None)
            if folded_prior is not None:
                result.prior_values[k] = folded_prior
        result.fields[k] = rv
    for k, v in receiver.prior_values.items():
        if k in receiver.fields:
            result.prior_values[k] = v
    return result
