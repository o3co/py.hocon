"""Value model for parsed/resolved HOCON trees.

Mirrors ts.hocon ``src/value.ts``. The three variants (object / array / scalar)
are plain classes discriminated by ``isinstance`` (Python's structural narrowing
replaces the TS ``kind`` discriminated union). Object fields use a ``dict``,
which preserves insertion order like the JS ``Map`` ts.hocon relies on.

Standalone ``as_*`` / ``is_*`` accessors mirror rs.hocon's ``HoconValue::as_*``
(a discriminated union has no methods of its own).
"""

from __future__ import annotations

from typing import Literal, TypeGuard

from .coerce import coerce_boolean, coerce_number

__all__ = [
    "HoconArray",
    "HoconObject",
    "HoconScalar",
    "HoconValue",
    "ScalarValueType",
    "as_array",
    "as_boolean",
    "as_number",
    "as_object",
    "as_string",
    "is_array",
    "is_null",
    "is_object",
    "is_scalar",
]

ScalarValueType = Literal["string", "number", "boolean", "null"]


class HoconObject:
    kind: Literal["object"] = "object"

    def __init__(self, fields: dict[str, HoconValue]) -> None:
        self.fields = fields


class HoconArray:
    kind: Literal["array"] = "array"

    def __init__(self, items: list[HoconValue]) -> None:
        self.items = items


class HoconScalar:
    kind: Literal["scalar"] = "scalar"

    def __init__(self, raw: str, value_type: ScalarValueType) -> None:
        self.raw = raw
        self.value_type = value_type


HoconValue = HoconObject | HoconArray | HoconScalar


# ─── value accessors ──────────────────────────────────────────────────────────


def as_string(v: HoconValue) -> str | None:
    """Scalar string only (strict): non-string scalars and containers → None."""
    if isinstance(v, HoconScalar) and v.value_type == "string":
        return v.raw
    return None


def as_number(v: HoconValue) -> float | None:
    """Scalar coerced to a number via :func:`coerce_number` (lenient)."""
    if isinstance(v, HoconScalar):
        return coerce_number(v.raw)
    return None


def as_boolean(v: HoconValue) -> bool | None:
    """Scalar coerced to a boolean (true/yes/on, false/no/off)."""
    if isinstance(v, HoconScalar):
        return coerce_boolean(v.raw)
    return None


def as_object(v: HoconValue) -> dict[str, HoconValue] | None:
    """The object's fields, or None if not an object."""
    return v.fields if isinstance(v, HoconObject) else None


def as_array(v: HoconValue) -> list[HoconValue] | None:
    """The array's items, or None if not an array."""
    return v.items if isinstance(v, HoconArray) else None


def is_object(v: HoconValue) -> TypeGuard[HoconObject]:
    return isinstance(v, HoconObject)


def is_array(v: HoconValue) -> TypeGuard[HoconArray]:
    return isinstance(v, HoconArray)


def is_scalar(v: HoconValue) -> TypeGuard[HoconScalar]:
    return isinstance(v, HoconScalar)


def is_null(v: HoconValue) -> bool:
    """True for a null scalar."""
    return isinstance(v, HoconScalar) and v.value_type == "null"
