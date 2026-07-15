"""Programmatic construction of resolved Configs (``from_map`` / ``empty``).

Mirrors ts.hocon ``src/value-factory.ts``. Keys are treated as plain keys (NOT
path expressions — ``"a.b"`` is a literal top-level key, not nested). Values are
coerced per E12 § "Value factories".
"""

from __future__ import annotations

import math
from typing import Any

from .config import Config
from .errors import ConfigError
from .value import HoconArray, HoconObject, HoconScalar, HoconValue

__all__ = ["empty", "from_map"]


def from_map(values: dict[str, Any], origin_description: str | None = None) -> Config:
    """Construct a resolved Config from a plain ``dict``."""
    fields = _coerce_object(values, "")
    return Config._from_resolved_value(HoconObject(fields), origin_description)


def empty(origin_description: str | None = None) -> Config:
    """Return a resolved Config with no keys (equivalent to ``from_map({})``)."""
    return Config._from_resolved_value(HoconObject({}), origin_description)


def _coerce_object(obj: dict[str, Any], at_path: str) -> dict[str, HoconValue]:
    fields: dict[str, HoconValue] = {}
    for k, v in obj.items():
        child_path = f"{at_path}.{k}" if at_path else k
        fields[str(k)] = _coerce_value(v, child_path)
    return fields


def _coerce_value(v: Any, at_path: str) -> HoconValue:
    if v is None:
        return HoconScalar("null", "null")
    # bool must precede int — bool is a subclass of int in Python.
    if isinstance(v, bool):
        return HoconScalar("true" if v else "false", "boolean")
    if isinstance(v, int):
        return HoconScalar(str(v), "number")
    if isinstance(v, float):
        if math.isnan(v) or math.isinf(v):
            raise ConfigError(
                f"from_map: {v} is not representable in HOCON "
                f'(NaN/Infinity not allowed) at path "{at_path}"',
                at_path,
            )
        return HoconScalar(_render_float(v), "number")
    if isinstance(v, str):
        return HoconScalar(v, "string")
    if isinstance(v, (list, tuple)):
        return HoconArray([_coerce_value(item, f"{at_path}[{i}]") for i, item in enumerate(v)])
    if isinstance(v, dict):
        return HoconObject(_coerce_object(v, at_path))
    raise ConfigError(
        f'from_map: unsupported value type "{type(v).__name__}" at path "{at_path}"',
        at_path,
    )


def _render_float(v: float) -> str:
    """Render a float like JS ``String(v)``: integral floats drop the ``.0``."""
    if v.is_integer():
        return str(int(v))
    return repr(v)
