"""``Config`` — the resolved-configuration handle returned by the parse entry points.

Mirrors ts.hocon ``src/config.ts``. Accessor naming follows rs.hocon's
snake_case surface (``get_string`` / ``get_number`` / ``get_duration`` …), which
is already idiomatic Python. Deferred-resolution state (``resolve`` /
``resolve_with`` / ``with_fallback``, NotResolvedError semantics) follows E12.
"""

from __future__ import annotations

import math
import re
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from typing import Any, TypeVar, cast, overload

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
    parse_period,
)
from .errors import ConfigError, NotResolvedError
from .numeric_array import numeric_object_to_array
from .render_hocon import render_root
from .value import HoconArray, HoconObject, HoconScalar, HoconValue, ScalarValueType

__all__ = ["Config", "Period"]

T = TypeVar("T")


@dataclass(frozen=True)
class Period:
    """A calendar period with year, month, and day components.

    Returned by :meth:`Config.get_period`. All fields are plain ``int``s;
    negative periods are permitted (matches Lightbend behaviour). New fields
    (e.g. weeks, hours) may be added in a future minor version — mirrors
    rs.hocon's ``#[non_exhaustive]`` ``Period`` struct.
    """

    years: int
    months: int
    days: int


class Config(Mapping[str, Any]):
    """Read-only :class:`~collections.abc.Mapping` over the top-level keys.

    Iteration / ``len`` / ``dict(config)`` operate on the top-level fields;
    ``config[path]`` and ``path in config`` additionally accept dotted path
    expressions (``config["server.host"]``), with a literal top-level key
    taking precedence over path traversal so that iteration → indexing
    round-trips for quoted keys that contain dots. Values decode to plain
    Python objects exactly like :meth:`get` / :meth:`to_object`.

    Being a ``Mapping`` gives dict-style semantics: equality is value-based
    (two Configs — or a Config and a ``dict`` — compare equal when their
    decoded content is equal), truthiness is emptiness, and Config is
    unhashable, all matching ``dict``.
    """

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

    # ─── Mapping protocol ─────────────────────────────────────────────────────

    def __getitem__(self, path: str) -> Any:
        # dict parity: a non-str key is simply absent (KeyError), it must not
        # leak a TypeError out of the path splitter.
        if not isinstance(path, str):
            raise KeyError(path)
        v = self._lookup_key_or_path(path)
        if v is None:
            raise KeyError(path)
        return _hocon_to_py(v)

    def __iter__(self) -> Iterator[str]:
        return iter(self._root.fields)

    def __len__(self) -> int:
        return len(self._root.fields)

    def __contains__(self, path: object) -> bool:
        if not isinstance(path, str):
            return False
        return self._lookup_key_or_path(path) is not None

    # ─── accessors ────────────────────────────────────────────────────────────

    def get(self, path: str, default: Any = None) -> Any:
        """Decoded value at ``path``, or ``default`` when the path is absent.

        An explicit HOCON ``null`` is a present value and decodes to ``None``
        (it does not fall back to ``default``), matching ``dict.get``.
        """
        if not isinstance(path, str):  # dict parity: non-str keys are absent
            return default
        v = self._lookup_key_or_path(path)
        if v is None:
            return default
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

    def get_period(self, path: str) -> Period:
        """Calendar :class:`Period` at ``path`` (S20.1–S20.4). Accepts
        ``"7d"`` / ``"2w"`` / ``"3m"`` / ``"1y"`` style strings or a bare
        integer, which is taken as days (HOCON.md L1321). Period is
        integer-only (Lightbend ``Integer.parseInt``): fractional values
        raise, unlike :meth:`get_duration` / :meth:`get_bytes`."""
        v = self._require_scalar(path)
        if v.value_type != "string" and v.value_type != "number":
            raise ConfigError(f"expected period at {path}, got {v.value_type}", path)
        parsed = parse_period(v.raw)
        if parsed is None:
            raise ConfigError(f"invalid period at {path}: {v.raw!r}", path)
        return Period(*parsed)

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
        return self._lookup_key_or_path(path) is not None

    # Pre-Mapping API returned a list; kept for backward compatibility over
    # typeshed's KeysView (iteration / len / `in` work the same on both).
    def keys(self) -> list[str]:  # type: ignore[override]
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

    # The Any overload keeps typing expressions that are not `type` objects
    # statically (e.g. `Optional[int]`, unparameterized aliases) usable; plain
    # classes and subscripted generics like `list[Server]` hit the first
    # overload and keep full inference.
    @overload
    def decode(self, cls: type[T], path: str | None = None) -> T: ...

    @overload
    def decode(self, cls: Any, path: str | None = None) -> Any: ...

    def decode(self, cls: Any, path: str | None = None) -> Any:
        """Decode the whole config — or the value at ``path`` — into ``cls``.

        ``cls`` may be a dataclass (constructed recursively, honouring type
        hints, field defaults, and ``field(metadata={"hocon": key})`` aliases),
        a class exposing ``model_validate`` (Pydantic v2 — the decoded plain
        object is delegated wholesale), or any supported type expression such
        as ``list[Server]`` or ``dict[str, int]`` when ``path`` points at a
        non-object node. Mirrors go.hocon ``Unmarshal`` / ``UnmarshalPath``:
        a field without a default whose key is absent is an error, extra keys
        are ignored, and int fields accept whole-number floats (wholeness
        derived from the decimal text). ``timedelta`` fields parse HOCON
        durations; :class:`Period` fields parse periods.

        Raises :class:`NotResolvedError` when the decoded subtree still
        contains unresolved substitutions, and :class:`ConfigError` on a
        missing path, a missing required field, or a type mismatch.
        """
        from .decode import decode_node

        if path is None:
            node: HoconValue = self._root
        else:
            found = self._lookup_node(path)
            if found is None:
                if not self._resolved and self._subtree_has_placeholders(path):
                    raise NotResolvedError(path)
                raise ConfigError(f"path not found: {path}", path)
            node = found
        if not self._resolved and self._subtree_has_placeholders(path or ""):
            raise NotResolvedError(path or "")
        return decode_node(node, cls, path or "")

    def render_hocon(self) -> str:
        """Render this resolved Config as HOCON text (E18).

        The output round-trips: parsing it back yields the same value tree.
        That is the correctness contract, not byte-for-byte formatting — a
        scalar is quoted whenever leaving it bare would re-parse as a
        different type (a string ``"8080"`` becomes ``"8080"``, not ``8080``),
        and left bare only when it provably cannot.

        The Config must be resolved and hold only data (objects, arrays,
        string / number / boolean / null scalars) — exactly what
        :func:`~hocon.from_map` and the format adapters produce. An unresolved
        Config raises :class:`NotResolvedError`; substitutions have no textual
        round trip through a value tree. Source comments are not represented —
        a value tree does not carry them.

        The root object's fields are emitted without enclosing braces, nested
        objects as ``key { … }``, arrays as newline-separated ``[ … ]``,
        indented two spaces.
        """
        if not self._resolved:
            raise NotResolvedError("")
        return render_root(self._root)

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

    def _lookup_key_or_path(self, path: str) -> HoconValue | None:
        """Literal top-level key first, then dotted-path traversal.

        The literal branch makes ``config[k]`` work for every ``k`` yielded by
        iteration, including quoted keys containing dots; on the (pathological)
        document that defines both, the literal key wins.
        """
        v = self._root.fields.get(path)
        if v is not None:
            return v
        return self._lookup_node(path)

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
