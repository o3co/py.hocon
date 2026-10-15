"""Typed decoding — resolved HOCON values into dataclass / Pydantic instances.

Mirrors go.hocon's ``Unmarshal`` / ``UnmarshalPath`` contract (required-field
errors, whole-float→int coercion derived from the decimal text per xx.hocon#56,
S15 numeric-keyed objects in sequence context, extra keys ignored) and
rs.hocon's serde integration, adapted to Python typing: nested dataclasses,
``list[T]`` / ``dict[str, T]`` / ``Optional[T]`` / ``Any``, ``timedelta`` for
durations, ``Period``, ``Enum``, nested ``Config``, ``Annotated`` unit markers
(:mod:`hocon.markers`), and duck-typed delegation to Pydantic v2's
``model_validate``.

Field-name resolution for dataclass fields: a ``field(metadata={"hocon":
key})`` alias, when present, is the *only* key consulted (like go.hocon's
``hocon:"..."`` tag and serde's ``rename`` — no fallback to the field name).
Otherwise the exact name, kebab-case (``pool_size`` → ``pool-size``), and
camelCase (``poolSize``) are tried in order, first match wins. An alias of
``"-"`` skips the field entirely (it must then have a default), mirroring
go.hocon's ``hocon:"-"`` tag.
"""

from __future__ import annotations

from dataclasses import MISSING, is_dataclass
from dataclasses import fields as dataclass_fields
from datetime import timedelta
from decimal import Decimal, InvalidOperation
from enum import Enum
from types import UnionType
from typing import Annotated, Any, Union, get_args, get_origin, get_type_hints

from .coerce import (
    UNIT_DURATION,
    UNIT_PERIOD,
    coerce_boolean,
    coerce_number,
    read_period,
    read_timedelta,
)
from .config import Config, Period, _hocon_to_py, _read_unit_scalar, _scalar_to_py
from .errors import ConfigError
from .markers import _decoding, _UnitMarker
from .numeric_array import numeric_object_to_array
from .value import HoconArray, HoconObject, HoconScalar, HoconValue

__all__ = ["decode_node"]


def decode_node(node: HoconValue, target: Any, path: str) -> Any:
    """Decode ``node`` into an instance of the ``target`` type expression."""
    if target is Any or target is object:
        return _hocon_to_py(node)

    origin = get_origin(target)
    if origin is Annotated:
        return _decode_annotated(node, target, path)
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
        return Period(*_read_unit_scalar(sc, path, UNIT_PERIOD, read_period))
    if target is timedelta:
        sc = _as_nonnull_scalar(node, target, path)
        return _read_unit_scalar(sc, path, UNIT_DURATION, read_timedelta)

    # Pydantic v2 (duck-typed so pydantic is never imported): hand the decoded
    # plain object to the model's own validator, which handles its own nesting.
    validate = getattr(target, "model_validate", None)
    if callable(validate):
        with _decoding():  # unit markers in the model read HOCON values
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


def _decode_annotated(node: HoconValue, target: Any, path: str) -> Any:
    # get_args flattens nested Annotated: (base, *metadata).
    base, *metadata = get_args(target)
    markers = [m for m in metadata if isinstance(m, _UnitMarker)]
    if not markers:
        return decode_node(node, base, path)  # metadata for someone else
    if len(markers) > 1:
        raise ConfigError(f"more than one unit marker on {target!r} at {_p(path)}", path)
    marker = markers[0]
    if _is_null(node):
        return decode_node(node, base, path)  # Optional → None, else the null error
    try:
        inner = marker.resolve_target(base)
    except TypeError as e:
        raise ConfigError(f"{e} at {_p(path)}", path) from None
    sc = _as_nonnull_scalar(node, base, path)
    value = _read_unit_scalar(sc, path, marker.what, lambda raw: marker.to_target(raw, inner))
    if inner is int and not isinstance(value, int):
        raise ConfigError(f"expected int at {_p(path)}, got {value!r} from {sc.raw!r}", path)
    if inner is float and isinstance(value, (int, float)):
        return float(value)
    return value


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
    hints = get_type_hints(target, include_extras=True)
    kwargs: dict[str, Any] = {}
    for f in dataclass_fields(target):
        if not f.init:
            continue
        alias = f.metadata.get("hocon") if f.metadata else None
        if alias == "-":
            # Explicitly skipped. Enforce the documented default requirement
            # here so the caller gets a ConfigError with the field path, not a
            # TypeError out of the dataclass constructor.
            if f.default is MISSING and f.default_factory is MISSING:
                skipped = _child(path, f.name)
                raise ConfigError(
                    f'field skipped via metadata {{"hocon": "-"}} needs a default: {skipped}',
                    skipped,
                )
            continue
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
