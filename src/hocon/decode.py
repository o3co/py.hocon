"""Typed decoding — resolved HOCON values into dataclass / Pydantic instances.

Mirrors go.hocon's ``Unmarshal`` / ``UnmarshalPath`` contract (required-field
errors, whole-float→int coercion derived from the decimal text per xx.hocon#56,
S15 numeric-keyed objects in sequence context, extra keys ignored) and
rs.hocon's serde integration, adapted to Python typing: nested dataclasses,
``list[T]`` / ``dict[str, T]`` / ``Optional[T]`` / ``Any``, ``timedelta`` for
durations, ``Period``, ``Enum``, nested ``Config``, and duck-typed delegation
to Pydantic v2's ``model_validate``.

Field-name resolution for dataclass fields, first match wins:
``field(metadata={"hocon": key})`` alias → exact name → kebab-case
(``pool_size`` → ``pool-size``) → camelCase (``pool_size`` → ``poolSize``).
An alias of ``"-"`` skips the field entirely (it must then have a default),
mirroring go.hocon's ``hocon:"-"`` tag.
"""

from __future__ import annotations

import math
from dataclasses import MISSING, is_dataclass
from dataclasses import fields as dataclass_fields
from datetime import timedelta
from decimal import Decimal, InvalidOperation
from enum import Enum
from types import UnionType
from typing import Any, Union, get_args, get_origin, get_type_hints

from .coerce import coerce_boolean, coerce_number, parse_duration, parse_period
from .config import Config, Period, _hocon_to_py, _scalar_to_py
from .errors import ConfigError
from .numeric_array import numeric_object_to_array
from .value import HoconArray, HoconObject, HoconScalar, HoconValue

__all__ = ["decode_node"]


def decode_node(node: HoconValue, target: Any, path: str) -> Any:
    """Decode ``node`` into an instance of the ``target`` type expression."""
    if target is Any or target is object:
        return _hocon_to_py(node)

    origin = get_origin(target)
    if origin is Union or origin is UnionType:
        return _decode_optional(node, target, path)
    if origin is list:
        args = get_args(target)
        elem_t = args[0] if args else Any
        items = _as_array_items(node, path)
        return [decode_node(item, elem_t, f"{path}[{i}]") for i, item in enumerate(items)]
    if origin is dict:
        args = get_args(target)
        key_t, val_t = args if args else (str, Any)
        if key_t is not str:
            raise ConfigError(f"unsupported dict key type {key_t!r} at {_p(path)}", path)
        obj = _as_object(node, target, path)
        return {k: decode_node(v, val_t, _child(path, k)) for k, v in obj.fields.items()}
    if origin is not None:
        raise ConfigError(f"unsupported target type {target!r} at {_p(path)}", path)

    if not isinstance(target, type):
        raise ConfigError(f"unsupported target type {target!r} at {_p(path)}", path)

    if target is Config:
        return Config(_as_object(node, target, path))
    if target is Period:
        sc = _as_nonnull_scalar(node, target, path)
        parsed = parse_period(sc.raw)
        if parsed is None:
            raise ConfigError(f"invalid period at {_p(path)}: {sc.raw!r}", path)
        return Period(*parsed)
    if target is timedelta:
        sc = _as_nonnull_scalar(node, target, path)
        ms = parse_duration(sc.raw)
        if math.isnan(ms):
            raise ConfigError(f"invalid duration at {_p(path)}: {sc.raw!r}", path)
        return timedelta(milliseconds=ms)

    # Pydantic v2 (duck-typed so pydantic is never imported): hand the decoded
    # plain object to the model's own validator, which handles its own nesting.
    validate = getattr(target, "model_validate", None)
    if callable(validate):
        return validate(_hocon_to_py(node))

    if issubclass(target, Enum):
        sc = _as_nonnull_scalar(node, target, path)
        value = _scalar_to_py(sc.raw, sc.value_type)
        try:
            return target(value)
        except ValueError:
            pass
        try:
            return target[sc.raw]
        except KeyError:
            raise ConfigError(
                f"invalid {target.__name__} at {_p(path)}: {sc.raw!r}", path
            ) from None

    if is_dataclass(target):
        return _decode_dataclass(node, target, path)

    if target in (str, bool, int, float):
        return _decode_scalar(node, target, path)

    raise ConfigError(f"unsupported target type {target!r} at {_p(path)}", path)


def _decode_optional(node: HoconValue, target: Any, path: str) -> Any:
    args = get_args(target)
    if _is_null(node) and type(None) in args:
        return None
    non_none = [a for a in args if a is not type(None)]
    if len(non_none) == 1 and len(args) == 2:
        return decode_node(node, non_none[0], path)
    raise ConfigError(
        f"unsupported union target {target!r} at {_p(path)} (only Optional[T] is supported)",
        path,
    )


def _decode_dataclass(node: HoconValue, target: type, path: str) -> Any:
    obj = _as_object(node, target, path)
    hints = get_type_hints(target)
    kwargs: dict[str, Any] = {}
    for f in dataclass_fields(target):
        if not f.init:
            continue
        alias = f.metadata.get("hocon") if f.metadata else None
        if alias == "-":
            continue  # explicitly skipped; the field must carry a default
        child: HoconValue | None = None
        found_key: str | None = None
        for cand in _key_candidates(f.name, alias):
            v = obj.fields.get(cand)
            if v is not None:
                child, found_key = v, cand
                break
        if child is None or found_key is None:
            if f.default is not MISSING or f.default_factory is not MISSING:
                continue  # dataclass default applies
            missing = _child(path, alias or f.name)
            raise ConfigError(f"missing required field at {missing}", missing)
        kwargs[f.name] = decode_node(child, hints.get(f.name, Any), _child(path, found_key))
    return target(**kwargs)


def _decode_scalar(node: HoconValue, target: type, path: str) -> Any:
    sc = _as_nonnull_scalar(node, target, path)
    if target is str:
        # Any non-null scalar decodes into str via its raw text (go.hocon
        # parity: quoted or unquoted numbers/booleans are accepted).
        return sc.raw
    if target is bool:
        b = coerce_boolean(sc.raw)
        if b is None:
            raise ConfigError(f"expected bool at {_p(path)}, got {sc.raw!r}", path)
        return b
    if target is int:
        n = coerce_number(sc.raw)
        if isinstance(n, int):
            return n
        whole = _float_spelled_whole_to_int(sc.raw)
        if whole is None:
            raise ConfigError(f"expected int at {_p(path)}, got {sc.raw!r}", path)
        return whole
    n = coerce_number(sc.raw)
    if n is None:
        raise ConfigError(f"expected float at {_p(path)}, got {sc.raw!r}", path)
    return float(n)


def _float_spelled_whole_to_int(raw: str) -> int | None:
    """Whole-number float/exponent text → exact int, or None.

    Wholeness and the value are derived from the decimal text, never through a
    float64 (xx.hocon#56) — mirrors go.hocon's ``wholeFloatToInt64`` and
    rs.hocon's ``whole_float_to_i64``. The magnitude is bounded at the
    siblings' ~i64 digit width, which also stops an exponent like ``1e999999``
    from allocating an astronomically large int. Plain integer literals never
    reach here (``coerce_number`` returns them as unbounded ``int``).
    """
    if not any(c in raw for c in ".eE"):
        return None
    try:
        d = Decimal(raw.strip())
    except InvalidOperation:
        return None
    if not d.is_finite() or d != d.to_integral_value():
        return None
    if d.adjusted() >= 19:
        return None
    return int(d.to_integral_value())


def _key_candidates(name: str, alias: str | None) -> list[str]:
    if alias is not None:
        return [alias]
    parts = name.split("_")
    camel = parts[0] + "".join(p.title() for p in parts[1:])
    out = [name]
    for cand in (name.replace("_", "-"), camel):
        if cand not in out:
            out.append(cand)
    return out


def _is_null(node: HoconValue) -> bool:
    return isinstance(node, HoconScalar) and node.value_type == "null"


def _as_object(node: HoconValue, target: Any, path: str) -> HoconObject:
    if not isinstance(node, HoconObject):
        raise ConfigError(
            f"expected object for {_t(target)} at {_p(path)}, got {node.kind}", path
        )
    return node


def _as_array_items(node: HoconValue, path: str) -> list[HoconValue]:
    # S15 parity: a numerically-keyed object converts to an array in sequence
    # context, matching get_list and the go/rs unmarshal paths.
    if isinstance(node, HoconObject):
        converted = numeric_object_to_array(node)
        if converted is not None:
            return list(converted)
    if not isinstance(node, HoconArray):
        raise ConfigError(f"expected array at {_p(path)}, got {node.kind}", path)
    return node.items


def _as_nonnull_scalar(node: HoconValue, target: Any, path: str) -> HoconScalar:
    if not isinstance(node, HoconScalar):
        raise ConfigError(
            f"expected scalar for {_t(target)} at {_p(path)}, got {node.kind}", path
        )
    if node.value_type == "null":
        # S17.6 parity: null never decodes into a non-optional type.
        raise ConfigError(
            f"null cannot decode into {_t(target)} at {_p(path)} (use Optional)", path
        )
    return node


def _child(path: str, key: str) -> str:
    return f"{path}.{key}" if path else key


def _p(path: str) -> str:
    return path or "<root>"


def _t(target: Any) -> str:
    return target.__name__ if isinstance(target, type) else repr(target)
