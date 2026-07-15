"""Pass 2: replaces substitution and concat placeholders with resolved values.

Mirrors ts.hocon ``src/internal/resolver/substitution-resolver.ts``. The
self-reference detection (owner gate + path walk), delayed object merge, S14c.2
original-path fallback, and S13c env-var-list expansion are ported line-for-line;
see the inline S-references for the governing spec items.
"""

from __future__ import annotations

import weakref
from typing import cast

from ...errors import ResolveError
from ...numeric_array import numeric_object_to_array
from ...value import HoconArray, HoconObject, HoconScalar, HoconValue
from .fold_self_ref import contains_subst_by_path, string_segments_to_key
from .types import (
    ConcatPlaceholder,
    ResObj,
    ResolveOptions,
    ResolverValue,
    SubstPlaceholder,
    is_concat,
    is_res_obj,
    is_subst,
    separator_values,
)
from .utils import (
    deep_merge_hocon_values,
    lookup_path,
    lookup_res_obj,
    segments_to_key,
)

__all__ = ["SubstitutionResolver"]


def _null_scalar() -> HoconScalar:
    return HoconScalar("null", "null")


class SubstitutionResolver:
    def __init__(self, root: ResObj, opts: ResolveOptions) -> None:
        self.root = root
        self.opts = opts
        self.resolving: set[str] = set()
        self.cache: dict[str, HoconValue] = {}
        # ConcatPlaceholder nodes currently mid-iteration (identity membership).
        self.resolving_concats: weakref.WeakSet[ConcatPlaceholder] = weakref.WeakSet()
        # Full dotted path of the field currently being assigned (owner gate).
        self.resolving_field_path: list[str] = []

    def _origin_prefix(self) -> str:
        return f"{self.opts.origin_description}: " if self.opts.origin_description else ""

    def resolve(self) -> HoconValue:
        return self._resolve_res_obj(self.root)

    def _resolve_res_obj(self, obj: ResObj) -> HoconValue:
        result: dict[str, HoconValue] = {}
        for key, val in obj.fields.items():
            self.resolving_field_path.append(key)
            full_cache_key = string_segments_to_key(self.resolving_field_path)
            self.cache.pop(full_cache_key, None)
            try:
                resolved = self._resolve_val(val, obj)
            finally:
                self.resolving_field_path.pop()
            if resolved is not None:
                # Delayed merge: if both current and prior resolve to objects, deep merge.
                if isinstance(resolved, HoconObject):
                    prior = obj.prior_values.get(key)
                    if prior is not None:
                        prior_resolved = self._resolve_val(prior, obj)
                        if isinstance(prior_resolved, HoconObject):
                            final_value = deep_merge_hocon_values(prior_resolved, resolved)
                            result[key] = final_value
                            self.cache[full_cache_key] = final_value
                            self._cache_descendants(full_cache_key, final_value)
                            continue
                result[key] = resolved
                self.cache[full_cache_key] = resolved
                self._cache_descendants(full_cache_key, resolved)
            else:
                # Unresolved optional substitution: fall back to prior value.
                prior = obj.prior_values.get(key)
                if prior is not None:
                    prior_resolved = self._resolve_val(prior, obj)
                    if prior_resolved is not None:
                        result[key] = prior_resolved
                        self.cache[full_cache_key] = prior_resolved
                        self._cache_descendants(full_cache_key, prior_resolved)
        return HoconObject(result)

    def _cache_descendants(self, prefix: str, value: HoconValue) -> None:
        if not isinstance(value, HoconObject):
            return
        for key, child in value.fields.items():
            child_key = f"{prefix}.{string_segments_to_key([key])}"
            self.cache[child_key] = child
            self._cache_descendants(child_key, child)

    def _resolve_val(self, v: ResolverValue, scope: ResObj) -> HoconValue | None:
        if is_subst(v):
            return self._resolve_subst(v, scope)
        if is_concat(v):
            # Mark mid-iteration so _resolve_subst can detect a true self-ref.
            self.resolving_concats.add(v)
            try:
                return self._resolve_concat(v.nodes, scope, v.line, v.col)
            finally:
                self.resolving_concats.discard(v)
        if is_res_obj(v):
            return self._resolve_res_obj(v)
        if isinstance(v, HoconArray):
            return HoconArray(
                [
                    (self._resolve_val(item, scope) or _null_scalar())
                    for item in v.items
                ]
            )
        # Exhausted every placeholder/container variant above; v is a resolved
        # HoconValue (scalar or object). TypeGuards don't narrow the negative
        # branch in mypy, so cast to the resolved contract.
        return cast("HoconValue", v)

    def _resolve_subst(self, s: SubstPlaceholder, scope: ResObj) -> HoconValue | None:
        if s.known_absent:
            return None

        # Cache key includes listSuffix so ${X} and ${X[]} never collide.
        key = f"{segments_to_key(s.segments)}[]" if s.list_suffix else segments_to_key(s.segments)

        if key in self.cache:
            return self.cache[key]

        if key in self.resolving:
            # Cycle detected: try prior value for self-referential substitutions.
            prior = self._lookup_prior(s, scope)
            if prior is not None:
                saved = self.resolving
                self.resolving = set(saved)
                try:
                    return self._resolve_val(prior, scope)
                finally:
                    self.resolving = saved
            if s.optional:
                return None
            raise ResolveError(
                self._origin_prefix() + f"circular substitution: {key}", key, s.line, s.col
            )

        self.resolving.add(key)
        try:
            found = lookup_path(self.root, s.segments)
            if found is not None:
                # S13a.13 / spec L841: self-ref detection (owner gate + path walk).
                rfp = self.resolving_field_path
                is_owner = len(rfp) >= len(s.segments) and all(
                    rfp[i] == s.segments[i].text for i in range(len(s.segments))
                )
                is_self_ref = (
                    is_concat(found) and found in self.resolving_concats
                ) or (is_owner and contains_subst_by_path(found, s.segments))
                if is_self_ref:
                    prior = self._lookup_prior(s, scope)
                    if prior is not None:
                        result = self._resolve_val(prior, scope)
                        if result is not None:
                            self.cache[key] = result
                        return result
                    if s.optional:
                        return None
                    raise ResolveError(
                        f"{self._origin_prefix()}could not resolve substitution: ${{{key}}}",
                        key,
                        s.line,
                        s.col,
                    )
                result = self._resolve_val(found, scope)
                # Delayed merge in substitution context.
                effective_len = len(s.segments) - s.prefix_len
                if effective_len == 1 and isinstance(result, HoconObject):
                    leaf_seg = s.segments[-1].text if s.segments else ""
                    if s.prefix_len > 0:
                        parent_scope = lookup_res_obj(self.root, s.segments[:-1])
                        prior = parent_scope.prior_values.get(leaf_seg) if parent_scope else None
                    else:
                        prior = scope.prior_values.get(leaf_seg) or self.root.prior_values.get(
                            leaf_seg
                        )
                    if prior is not None:
                        prior_resolved = self._resolve_val(prior, scope)
                        if isinstance(prior_resolved, HoconObject):
                            result = deep_merge_hocon_values(prior_resolved, result)
                if result is not None:
                    self.cache[key] = result
                return result

            # S14c.2 (xx.hocon#22 C4): original-path config fallback for
            # relativized substitutions. Tried after the relativized lookup
            # misses, before env-var fallback.
            if s.prefix_len > 0 and len(s.segments) > s.prefix_len:
                original_segments = s.segments[s.prefix_len :]
                fallback_found = lookup_path(self.root, original_segments)
                if fallback_found is not None:
                    result = self._resolve_val(fallback_found, scope)
                    if len(original_segments) == 1 and isinstance(result, HoconObject):
                        root_seg = original_segments[0].text if original_segments else ""
                        prior = self.root.prior_values.get(root_seg)
                        if prior is not None:
                            prior_resolved = self._resolve_val(prior, scope)
                            if isinstance(prior_resolved, HoconObject):
                                result = deep_merge_hocon_values(prior_resolved, result)
                    if result is not None:
                        self.cache[key] = result
                    return result

            # S13c: env-var list expansion — gated on useSystemEnvironment.
            if s.list_suffix and self.opts.use_system_environment is not False:
                env_result = self._resolve_env_list(s)
                if env_result is not None:
                    self.cache[key] = env_result
                    return env_result
                if s.optional:
                    return None
                env_base = ".".join(seg.text for seg in s.segments)
                raise ResolveError(
                    f"{self._origin_prefix()}could not resolve substitution: ${{{key}}} "
                    f"(no environment variables {env_base}_0, {env_base}_1, … set)",
                    key,
                    s.line,
                    s.col,
                )
            elif s.list_suffix:
                if s.optional:
                    return None
                if self.opts.allow_unresolved:
                    return cast(HoconValue, s)
                raise ResolveError(
                    f"{self._origin_prefix()}could not resolve substitution: ${{{key}}}",
                    key,
                    s.line,
                    s.col,
                )

            # Env var fallback — raw dot-join (no quoting), Lightbend-aligned.
            if self.opts.use_system_environment is not False:
                env_key = ".".join(seg.text for seg in s.segments)
                env_val = self.opts.env.get(env_key)
                if env_val is None and s.prefix_len > 0:
                    env_val = self.opts.env.get(
                        ".".join(seg.text for seg in s.segments[s.prefix_len :])
                    )
                if env_val is not None:
                    result_scalar = HoconScalar(env_val, "string")
                    self.cache[key] = result_scalar
                    return result_scalar

            if s.optional:
                return None
            if self.opts.allow_unresolved:
                return cast(HoconValue, s)
            raise ResolveError(
                f"{self._origin_prefix()}could not resolve substitution: ${{{key}}}",
                key,
                s.line,
                s.col,
            )
        finally:
            self.resolving.discard(key)

    def _lookup_prior(self, s: SubstPlaceholder, scope: ResObj) -> ResolverValue | None:
        """Prior lookup shared by the cycle-guard and self-ref short-circuit
        branches (dotted-path-at-root uses ``len(segments) > 1``)."""
        if len(s.segments) > 1:
            leaf_seg = s.segments[-1].text
            parent_scope = lookup_res_obj(self.root, s.segments[:-1])
            return parent_scope.prior_values.get(leaf_seg) if parent_scope else None
        root_seg = s.segments[0].text if s.segments else ""
        return scope.prior_values.get(root_seg) or self.root.prior_values.get(root_seg)

    def _resolve_env_list(self, s: SubstPlaceholder) -> HoconValue | None:
        """S13c: scan environment for NAME_0, NAME_1, … → Array<Scalar(String)>.
        First candidate base whose _0 is present wins entirely."""
        for base in self._candidate_bases(s):
            key0 = base + "_0"
            if key0 not in self.opts.env:
                continue
            items: list[HoconValue] = []
            i = 0
            while True:
                k = f"{base}_{i}"
                if k not in self.opts.env:
                    break
                items.append(HoconScalar(self.opts.env[k], "string"))
                i += 1
            return HoconArray(items)
        return None

    def _candidate_bases(self, s: SubstPlaceholder) -> list[str]:
        full = ".".join(seg.text for seg in s.segments)
        if s.prefix_len == 0:
            return [full]
        bare = ".".join(seg.text for seg in s.segments[s.prefix_len :])
        return [full, bare]

    def _resolve_concat(
        self, nodes: list[ResolverValue], scope: ResObj, line: int = 0, col: int = 0
    ) -> HoconValue | None:
        raw_resolved = [self._resolve_val(n, scope) for n in nodes]

        if self.opts.allow_unresolved:
            for v in raw_resolved:
                if v is not None and is_subst(cast(ResolverValue, v)):
                    return v

        resolved = [v for v in raw_resolved if v is not None]

        if len(resolved) == 0:
            return None
        if len(resolved) == 1:
            return resolved[0]

        # Filter parser-inserted separator whitespace (tracked via WeakSet), NOT
        # user-authored '' / ' ' which should prevent object merging.
        non_sep = [
            v
            for v in resolved
            if not (isinstance(v, HoconScalar) and v in separator_values)
        ]

        if len(non_sep) == 0:
            s = "".join(
                v.raw if isinstance(v, HoconScalar) else _json_dumps(v) for v in resolved
            )
            return HoconScalar(s, "string")

        # True left-to-right pairwise fold (S10.4 / S10.13 / S10.19).
        def join_pair(left: HoconValue, right: HoconValue) -> HoconValue:
            if isinstance(left, HoconObject) and isinstance(right, HoconObject):
                return deep_merge_hocon_values(left, right)
            if isinstance(left, HoconArray) and isinstance(right, HoconObject):
                converted = numeric_object_to_array(right)
                if converted is not None:
                    return HoconArray([*left.items, *converted])
                raise ResolveError(
                    "cannot concatenate array with object: value concatenation requires "
                    "same-kind operands (S10.4)",
                    "",
                    line,
                    col,
                )
            if isinstance(left, HoconObject) and isinstance(right, HoconArray):
                converted = numeric_object_to_array(left)
                if converted is not None:
                    return HoconArray([*converted, *right.items])
                raise ResolveError(
                    "cannot concatenate object with array: value concatenation requires "
                    "same-kind operands (S10.4)",
                    "",
                    line,
                    col,
                )
            if isinstance(left, HoconArray) and isinstance(right, HoconArray):
                return HoconArray([*left.items, *right.items])
            if isinstance(left, HoconArray) or isinstance(right, HoconArray):
                raise ResolveError(
                    f"cannot concatenate {left.kind} with {right.kind}: arrays and objects "
                    f"may not appear in string value concatenation (S10.13)",
                    "",
                    line,
                    col,
                )
            if isinstance(left, HoconObject) or isinstance(right, HoconObject):
                raise ResolveError(
                    f"cannot concatenate {left.kind} with {right.kind}: arrays and objects "
                    f"may not appear in string value concatenation (S10.13)",
                    "",
                    line,
                    col,
                )
            # Scalar + Scalar — string concat (S10).
            return HoconScalar(left.raw + right.raw, "string")

        folded = non_sep[0]
        for nxt in non_sep[1:]:
            folded = join_pair(folded, nxt)

        # If scalar and there were separator tokens, re-run as plain string concat
        # over ALL resolved values so whitespace is preserved.
        if isinstance(folded, HoconScalar):
            s = "".join(
                v.raw if isinstance(v, HoconScalar) else _json_dumps(v) for v in resolved
            )
            return HoconScalar(s, "string")

        return folded


def _json_dumps(v: HoconValue) -> str:
    """Defensive-only stringification for a non-scalar value inside string
    concat. Both call sites already special-case scalars, and ``join_pair``
    rejects arrays/objects in string concatenation before this fold path is
    taken (S10.13), so this is unreachable for valid input."""
    return ""
