"""``Config`` — the resolved-configuration handle returned by the parse entry points.

Mirrors ts.hocon ``src/config.ts``. Accessor naming follows rs.hocon's
snake_case surface (``get_string`` / ``get_number`` / ``get_duration`` …), which
is already idiomatic Python. Deferred-resolution state (``resolve`` /
``resolve_with`` / ``with_fallback``, NotResolvedError semantics) follows E12.
"""

from __future__ import annotations

import math
import re
from typing import Any, cast

from ._internal.resolver.resolver import (
    build_partial_hocon_from_res_obj,
    contains_placeholders,
    hocon_value_to_res_obj,
    resolve_tree,
    val_contains_placeholders,
)
from ._internal.resolver.types import (
    ConcatPlaceholder,
    ResObj,
    ResolveOptions,
    SubstPlaceholder,
    is_concat,
    is_res_obj,
    is_subst,
    merge_unresolved,
)
from .coerce import (
    ByteUnit,
    DurationUnit,
    coerce_boolean,
    coerce_number,
    parse_bytes,
    parse_duration,
)
from .errors import ConfigError, NotResolvedError
from .numeric_array import numeric_object_to_array
from .value import HoconArray, HoconObject, HoconScalar, HoconValue, ScalarValueType

__all__ = ["Config"]


class Config:
    def __init__(
        self,
        root: HoconObject,
        *,
        resolved: bool = True,
        parse_base_dir: str | None = None,
        origin_description: str | None = None,
        res_obj_root: ResObj | None = None,
        resolve_opts: ResolveOptions | None = None,
    ) -> None:
        self._root = root
        self._resolved = resolved
        self._parse_base_dir = parse_base_dir
        self._origin_description = origin_description
        self._res_obj_root = res_obj_root
        self._resolve_opts = resolve_opts

    # ─── construction ─────────────────────────────────────────────────────────

    def is_resolved(self) -> bool:
        """True when the value tree contains no unresolved substitution
        placeholders (whole-config granularity, E12 decision 11)."""
        return self._resolved

    @staticmethod
    def _from_resolved_value(
        root: HoconObject, origin_description: str | None = None
    ) -> Config:
        return Config(root, resolved=True, origin_description=origin_description)

    @staticmethod
    def _from_unresolved_res_obj(
        tree: ResObj,
        *,
        parse_base_dir: str | None,
        origin_description: str | None,
        resolved: bool,
        resolve_opts: ResolveOptions,
    ) -> Config:
        partial_root = build_partial_hocon_from_res_obj(tree)
        return Config(
            partial_root,
            resolved=resolved,
            parse_base_dir=parse_base_dir,
            origin_description=origin_description,
            res_obj_root=tree,
            resolve_opts=resolve_opts,
        )

    # ─── accessors ────────────────────────────────────────────────────────────

    def get(self, path: str) -> Any:
        v = self._lookup_node(path)
        if v is None:
            return None
        return _hocon_to_py(v)

    def get_value(self, path: str) -> HoconValue | None:
        """Raw HoconValue node at ``path`` for structural introspection, or None
        if absent. Raises NotResolvedError when the node/subtree is unresolved."""
        v = self._lookup_node(path)
        if v is None:
            if not self._resolved and self._subtree_has_placeholders(path):
                raise NotResolvedError(path)
            return None
        if (
            not isinstance(v, HoconScalar)
            and not self._resolved
            and self._subtree_has_placeholders(path)
        ):
            raise NotResolvedError(path)
        return v

    def get_string(self, path: str) -> str:
        v = self._require_scalar(path)
        # S17.6 (HOCON.md L1252): null → any non-null type is an error.
        if v.value_type == "null":
            raise ConfigError(f"expected string at {path}, got {v.value_type}", path)
        return v.raw

    def get_number(self, path: str) -> float | int:
        v = self._require_scalar(path)
        coerced = coerce_number(v.raw)
        if coerced is not None:
            return coerced
        raise ConfigError(f"expected number at {path}, got {v.value_type}", path)

    def get_int(self, path: str) -> int:
        """Convenience: :meth:`get_number` truncated to an ``int``."""
        return int(self.get_number(path))

    def get_float(self, path: str) -> float:
        """Convenience: :meth:`get_number` as a ``float``."""
        return float(self.get_number(path))

    def get_boolean(self, path: str) -> bool:
        v = self._require_scalar(path)
        coerced = coerce_boolean(v.raw)
        if coerced is not None:
            return coerced
        raise ConfigError(f"expected boolean at {path}, got {v.value_type}", path)

    def get_duration(self, path: str, unit: DurationUnit | None = None) -> float:
        v = self._require_scalar(path)
        if v.value_type != "string" and v.value_type != "number":
            raise ConfigError(f"expected duration at {path}, got {v.value_type}", path)
        result = parse_duration(v.raw, unit)
        if math.isnan(result):
            raise ConfigError(f"invalid duration at {path}: {v.raw!r}", path)
        return result

    def get_bytes(self, path: str, unit: ByteUnit | None = None) -> float:
        v = self._require_scalar(path)
        if v.value_type != "string" and v.value_type != "number":
            raise ConfigError(f"expected byte size at {path}, got {v.value_type}", path)
        result = parse_bytes(v.raw, unit)
        if math.isnan(result):
            raise ConfigError(f"invalid byte size at {path}: {v.raw!r}", path)
        if result < 0:
            raise ConfigError(f"byte size must be non-negative at {path}: {v.raw!r}", path)
        return result

    def get_config(self, path: str) -> Config:
        v = self._lookup_node(path)
        if v is None:
            if not self._resolved and self._subtree_has_placeholders(path):
                raise NotResolvedError(path)
            raise ConfigError(f"path not found: {path}", path)
        if not isinstance(v, HoconObject):
            raise ConfigError(f"expected object at {path}", path)
        if not self._resolved and self._subtree_has_placeholders(path):
            raise NotResolvedError(path)
        return Config(v, resolved=self._resolved)

    def get_list(self, path: str) -> list[Any]:
        v = self._lookup_node(path)
        if v is None:
            if not self._resolved and self._subtree_has_placeholders(path):
                raise NotResolvedError(path)
            raise ConfigError(f"path not found: {path}", path)
        if not self._resolved and self._subtree_has_placeholders(path):
            raise NotResolvedError(path)
        # S15: numerically-keyed object → array before the type check.
        if isinstance(v, HoconObject):
            converted = numeric_object_to_array(v)
            if converted is not None:
                return [_hocon_to_py(x) for x in converted]
        if not isinstance(v, HoconArray):
            raise ConfigError(f"expected array at {path}", path)
        return [_hocon_to_py(x) for x in v.items]

    def has(self, path: str) -> bool:
        return self._lookup_node(path) is not None

    def keys(self) -> list[str]:
        return list(self._root.fields.keys())

    def with_fallback(self, fallback: Config | None) -> Config:
        if fallback is None:
            return self
        self_tree = self._res_obj_root or hocon_value_to_res_obj(self._root)
        fb_tree = fallback._res_obj_root or hocon_value_to_res_obj(fallback._root)
        merged = merge_unresolved(self_tree, fb_tree)
        has_placeholders = contains_placeholders(merged)
        partial_root = build_partial_hocon_from_res_obj(merged)
        return Config(
            partial_root,
            resolved=not has_placeholders,
            parse_base_dir=self._parse_base_dir,
            origin_description=self._origin_description,
            res_obj_root=merged,
            resolve_opts=self._resolve_opts or fallback._resolve_opts,
        )

    def resolve(
        self, *, allow_unresolved: bool = False, use_system_environment: bool = True
    ) -> Config:
        """Run substitution resolution (phase 2) on the stored unresolved tree.
        Idempotent on an already-resolved Config (E12 decision 3)."""
        if self._resolved:
            return Config(
                self._root,
                resolved=True,
                parse_base_dir=self._parse_base_dir,
                origin_description=self._origin_description,
            )
        tree = self._res_obj_root
        if tree is None:
            return Config(self._root, resolved=True)

        resolve_opts = self._effective_resolve_opts(allow_unresolved, use_system_environment)
        resolved = resolve_tree(tree, resolve_opts)
        if not isinstance(resolved, HoconObject):
            raise RuntimeError("resolve: expected object root")

        if allow_unresolved:
            stripped, had_placeholders = _strip_placeholder_fields(resolved)
            return Config(
                stripped,
                resolved=not had_placeholders,
                parse_base_dir=self._parse_base_dir,
                origin_description=self._origin_description,
                res_obj_root=tree if had_placeholders else None,
                resolve_opts=resolve_opts if had_placeholders else None,
            )

        return Config(
            resolved,
            resolved=True,
            parse_base_dir=self._parse_base_dir,
            origin_description=self._origin_description,
        )

    def resolve_with(
        self,
        source: Config,
        *,
        allow_unresolved: bool = False,
        use_system_environment: bool = True,
    ) -> Config:
        """Resolve receiver substitutions using ``source`` as lookup context;
        source's keys are NOT merged into the result (E12 decisions 9, 10)."""
        if not source.is_resolved():
            raise NotResolvedError("source")
        if self._resolved:
            return Config(
                self._root,
                resolved=True,
                parse_base_dir=self._parse_base_dir,
                origin_description=self._origin_description,
            )

        receiver_tree = self._res_obj_root or hocon_value_to_res_obj(self._root)
        src_tree = hocon_value_to_res_obj(source._root)
        merged = merge_unresolved(receiver_tree, src_tree)

        resolve_opts = self._effective_resolve_opts(allow_unresolved, use_system_environment)
        resolved = resolve_tree(merged, resolve_opts)
        if not isinstance(resolved, HoconObject):
            raise RuntimeError("resolve_with: expected object root")

        receiver_shape = _res_obj_to_key_shape(receiver_tree)
        filtered = _filter_by_receiver_shape(resolved, receiver_shape)

        if allow_unresolved:
            stripped, had_placeholders = _strip_placeholder_fields(filtered)
            return Config(
                stripped,
                resolved=not had_placeholders,
                parse_base_dir=self._parse_base_dir,
                origin_description=self._origin_description,
                res_obj_root=receiver_tree if had_placeholders else None,
                resolve_opts=resolve_opts if had_placeholders else None,
            )

        return Config(
            filtered,
            resolved=True,
            parse_base_dir=self._parse_base_dir,
            origin_description=self._origin_description,
        )

    def to_object(self) -> Any:
        return _hocon_to_py(self._root)

    def _render_json_for_test(self) -> str:
        """Test-only: render this resolved Config as canonical JSON (sorted keys,
        no whitespace). Used by the conformance harness. Raises on placeholders."""
        return _render_hocon_as_json(self._root)

    # ─── internals ────────────────────────────────────────────────────────────

    def _effective_resolve_opts(
        self, allow_unresolved: bool, use_system_environment: bool
    ) -> ResolveOptions:
        import dataclasses

        base = self._resolve_opts or ResolveOptions()
        return dataclasses.replace(
            base,
            allow_unresolved=allow_unresolved,
            use_system_environment=use_system_environment,
            origin_description=self._origin_description,
        )

    def _lookup_node(self, path: str) -> HoconValue | None:
        segments = _split_config_path(path)
        current: HoconValue = self._root
        for seg in segments:
            if not isinstance(current, HoconObject):
                return None
            nxt = current.fields.get(seg)
            if nxt is None:
                return None
            current = nxt
        return current

    def _subtree_has_placeholders(self, path: str) -> bool:
        tree = self._res_obj_root
        if tree is None:
            return False
        segments = _split_config_path(path)
        cur: ResObj = tree
        for seg in segments:
            val = cur.fields.get(seg)
            if val is None:
                return False
            if is_res_obj(val):
                cur = val
            else:
                return val_contains_placeholders(val)
        return contains_placeholders(cur)

    def _require_scalar(self, path: str) -> HoconScalar:
        v = self._lookup_node(path)
        if v is None:
            if not self._resolved and self._subtree_has_placeholders(path):
                raise NotResolvedError(path)
            raise ConfigError(f"path not found: {path}", path)
        if not isinstance(v, HoconScalar):
            raise ConfigError(f"expected scalar at {path}, got {v.kind}", path)
        return v


def _split_config_path(path: str) -> list[str]:
    segments: list[str] = []
    i = 0
    while i < len(path):
        if path[i] == '"':
            i += 1
            segment = ""
            closed = False
            while i < len(path):
                ch = path[i]
                if ch == "\\" and i + 1 < len(path):
                    segment += path[i + 1]
                    i += 2
                    continue
                if ch == '"':
                    closed = True
                    i += 1
                    break
                segment += ch
                i += 1
            if not closed:
                raise ConfigError(f"unterminated quoted path segment: {path}", path)
            segments.append(segment)
            if i < len(path) and path[i] == ".":
                i += 1
        else:
            dot = path.find(".", i)
            if dot == -1:
                segments.append(path[i:])
                break
            segments.append(path[i:dot])
            i = dot + 1
    return segments


def _scalar_to_py(raw: str, value_type: ScalarValueType) -> Any:
    if value_type == "null":
        return None
    if value_type == "boolean":
        return raw == "true"
    if value_type == "number":
        coerced = coerce_number(raw)
        return coerced if coerced is not None else raw
    return raw


def _hocon_to_py(v: HoconValue) -> Any:
    if isinstance(v, HoconScalar):
        return _scalar_to_py(v.raw, v.value_type)
    if isinstance(v, HoconArray):
        return [_hocon_to_py(item) for item in v.items]
    return {k: _hocon_to_py(val) for k, val in v.fields.items()}


def _res_obj_to_key_shape(tree: ResObj) -> HoconObject:
    fields: dict[str, HoconValue] = {}
    for k, v in tree.fields.items():
        if is_subst(v) or is_concat(v):
            fields[k] = HoconScalar("", "null")
        elif is_res_obj(v):
            fields[k] = _res_obj_to_key_shape(v)
        else:
            # Neither placeholder nor ResObj → a plain HoconValue.
            fields[k] = cast("HoconValue", v)
    return HoconObject(fields)


def _strip_placeholder_fields(v: HoconObject) -> tuple[HoconObject, bool]:
    fields: dict[str, HoconValue] = {}
    had_placeholders = False
    for k, val in v.fields.items():
        if isinstance(val, (SubstPlaceholder, ConcatPlaceholder)):
            had_placeholders = True
        elif isinstance(val, HoconObject):
            inner, inner_had = _strip_placeholder_fields(val)
            if inner_had:
                had_placeholders = True
            fields[k] = inner
        else:
            fields[k] = val
    return HoconObject(fields), had_placeholders


def _filter_by_receiver_shape(resolved: HoconObject, receiver_shape: HoconObject) -> HoconObject:
    fields: dict[str, HoconValue] = {}
    for k, rv in resolved.fields.items():
        if k not in receiver_shape.fields:
            continue
        receiver_val = receiver_shape.fields[k]
        if isinstance(rv, HoconObject) and isinstance(receiver_val, HoconObject):
            fields[k] = _filter_by_receiver_shape(rv, receiver_val)
        else:
            fields[k] = rv
    return HoconObject(fields)


# RFC 8259 JSON number grammar — gates the numeric render fast-path.
_JSON_NUMBER_RE = re.compile(r"-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?")
_LEADING_ZERO_RE = re.compile(r"^([+-]?)0+(\d)")


def _normalize_leading_zero_number(raw: str) -> str:
    return _LEADING_ZERO_RE.sub(r"\1\2", raw)


def _render_hocon_as_json(v: HoconValue) -> str:
    import json

    if isinstance(v, HoconScalar):
        if v.value_type == "null":
            return "null"
        if v.value_type == "boolean":
            return v.raw
        if v.value_type == "number":
            norm = _normalize_leading_zero_number(v.raw)
            return norm if _JSON_NUMBER_RE.fullmatch(norm) else json.dumps(v.raw)
        return json.dumps(v.raw)
    if isinstance(v, HoconArray):
        return "[" + ",".join(_render_hocon_as_json(item) for item in v.items) + "]"
    keys = sorted(v.fields.keys())
    pairs = [f"{json.dumps(k)}:{_render_hocon_as_json(v.fields[k])}" for k in keys]
    return "{" + ",".join(pairs) + "}"
