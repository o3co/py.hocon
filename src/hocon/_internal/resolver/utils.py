"""Resolver helpers. Mirrors ts.hocon ``src/internal/resolver/utils.ts``.

Path lookup, deep-merge (both ``HoconValue`` and ``ResObj`` variants), and the
cross-include splice logic (go.hocon#134, S13b.2).
"""

from __future__ import annotations

import re

from ...value import HoconObject, HoconValue
from ..lexer.token import Segment
from .fold_self_ref import (
    fold_known_absent_self_ref,
    fold_or_skip_prior,
    string_segments_to_key,
)
from .types import ResObj, ResolverValue, is_res_obj, make_res_obj

__all__ = [
    "deep_merge_hocon_values",
    "deep_merge_res_obj_into",
    "hocon_value_to_res_obj",
    "is_file_not_found_error",
    "lookup_path",
    "lookup_res_obj",
    "segments_to_key",
]

_NON_BARE_KEY = re.compile(r"[^a-zA-Z0-9\-_]")


def segments_to_key(segments: list[Segment]) -> str:
    parts = []
    for s in segments:
        t = s.text
        if t == "" or _NON_BARE_KEY.search(t):
            parts.append('"' + t.replace("\\", "\\\\").replace('"', '\\"') + '"')
        else:
            parts.append(t)
    return ".".join(parts)


def lookup_path(root: ResObj, segments: list[Segment]) -> ResolverValue | None:
    if len(segments) == 0:
        return None
    head, tail = segments[0], segments[1:]
    key = head.text
    val = root.fields.get(key)
    if val is None:
        return None
    if len(tail) == 0:
        return val
    if is_res_obj(val):
        return lookup_path(val, tail)
    return None


def lookup_res_obj(root: ResObj, segments: list[Segment]) -> ResObj | None:
    cur: ResObj = root
    for seg in segments:
        val = cur.fields.get(seg.text)
        if val is None or not is_res_obj(val):
            return None
        cur = val
    return cur


def deep_merge_hocon_values(base: HoconObject, overlay: HoconObject) -> HoconObject:
    merged: dict[str, HoconValue] = dict(base.fields)
    for k, v in overlay.fields.items():
        existing = merged.get(k)
        if isinstance(existing, HoconObject) and isinstance(v, HoconObject):
            merged[k] = deep_merge_hocon_values(existing, v)
        else:
            merged[k] = v
    return HoconObject(merged)


def deep_merge_res_obj_into(
    dst: ResObj, src: ResObj, path_prefix: list[str] | None = None
) -> None:
    if path_prefix is None:
        path_prefix = []
    for k, src_val in src.fields.items():
        child_prefix = [*path_prefix, k]
        full_key = string_segments_to_key(child_prefix)
        dst_val = dst.fields.get(k)
        if dst_val is not None and is_res_obj(dst_val) and is_res_obj(src_val):
            # #120: save dst's pre-merge value as the prior at the OUTER level
            # even when both sides are objects and we recurse.
            prior_existing = dst.prior_values.get(k)
            prior = fold_or_skip_prior(dst_val, full_key, prior_existing)
            if prior is not None:
                dst.prior_values[k] = prior
            deep_merge_res_obj_into(dst_val, src_val, child_prefix)
        else:
            # Non-object collision: distinguish how src's value composes with
            # dst's pre-merge value (go.hocon#134, S13b.2).
            if dst_val is not None:
                if k in src.reset_keys:
                    dst.prior_values.pop(k, None)
                else:
                    dst_folded = fold_or_skip_prior(dst_val, full_key, dst.prior_values.get(k))
                    if dst_folded is not None:
                        src_prior = src.prior_values.get(k)
                        if src_prior is not None:
                            dst.prior_values[k] = fold_known_absent_self_ref(
                                src_prior, full_key, dst_folded
                            )
                        else:
                            dst.prior_values[k] = dst_folded
            dst.fields[k] = src_val
    # Carry over priors src has that dst lacks.
    for k, src_prior in src.prior_values.items():
        if k not in dst.prior_values:
            dst.prior_values[k] = src_prior
    # Propagate reset origin (union).
    for k in src.reset_keys:
        dst.reset_keys.add(k)


def hocon_value_to_res_obj(hv: HoconValue) -> ResObj:
    obj = make_res_obj()
    if not isinstance(hv, HoconObject):
        return obj
    for key, val in hv.fields.items():
        if isinstance(val, HoconObject):
            obj.fields[key] = hocon_value_to_res_obj(val)
        else:
            obj.fields[key] = val
    return obj


def is_file_not_found_error(e: BaseException) -> bool:
    if isinstance(e, FileNotFoundError):
        return True
    if isinstance(e, OSError):
        import errno

        if e.errno == errno.ENOENT:
            return True
    msg = str(e).lower()
    return "not found" in msg or "no such file" in msg or "enoent" in msg
