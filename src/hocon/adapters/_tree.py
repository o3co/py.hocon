"""Shared leaf normalization for the nested formats (JSONC, TOML, YAML).

These formats decode into dicts and lists already, so the only work left is
enforcing the object-root rule and mapping each leaf onto a type
:func:`hocon.from_map` accepts. The per-format leaf rules differ, so callers
supply those.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from datetime import date, datetime, time
from typing import Any

from ..value_factory import INT64_MAX, INT64_MIN
from . import AdapterError

__all__ = ["object_root", "convert"]


def object_root(doc: Any, fmt: str, scalar: Callable[[Any, str], Any]) -> dict[str, Any]:
    """Normalize ``doc``, which must be a mapping (spec F0.3)."""
    if not isinstance(doc, dict):
        kind = "a list" if isinstance(doc, list) else f"a {type(doc).__name__}"
        raise AdapterError(
            f"{fmt}: document root is {kind}, but a config root must be an object (spec F0.3)"
        )
    result = convert(doc, "", fmt, scalar)
    assert isinstance(result, dict)
    return result


def convert(v: Any, at: str, fmt: str, scalar: Callable[[Any, str], Any]) -> Any:
    if isinstance(v, dict):
        out: dict[str, Any] = {}
        for k, e in v.items():
            key = _key_string(k, at, fmt)
            out[key] = convert(e, key if at == "" else f"{at}.{key}", fmt, scalar)
        return out
    if isinstance(v, (list, tuple)):
        return [convert(e, f"{at}[{i}]", fmt, scalar) for i, e in enumerate(v)]
    return scalar(v, at)


def _key_string(k: Any, at: str, fmt: str) -> str:
    """Non-string scalar keys map to their string forms (spec F5.3)."""
    if isinstance(k, str):
        return k
    if isinstance(k, bool):
        return "true" if k else "false"
    if isinstance(k, (int, float)):
        return str(k)
    if k is None:
        return "null"
    raise AdapterError(
        f"{fmt}: at {at or 'document root'}: a {type(k).__name__} key is not usable "
        "as an object key (spec F5.3)"
    )


def common_scalar(v: Any, at: str, fmt: str) -> Any:
    """Leaf rules every nested format shares."""
    if v is None or isinstance(v, (bool, str)):
        return v
    if isinstance(v, int):
        # F0.5 — integers are int64. Python's int is unbounded and its JSON and
        # TOML decoders will happily hand back a wider one, so a document that
        # no sibling implementation can hold would otherwise load here.
        if not INT64_MIN <= v <= INT64_MAX:
            raise AdapterError(
                f"{fmt}: at {at or 'document root'}: {v} is outside the int64 range "
                "HOCON integers use (spec F0.5)"
            )
        return v
    if isinstance(v, float):
        if math.isnan(v) or math.isinf(v):
            raise AdapterError(
                f"{fmt}: at {at}: {v} is not representable in HOCON (spec F0.6)"
            )
        return v
    if isinstance(v, (datetime, date, time)):
        # HOCON has no datetime, so ISO text is the honest form — the same
        # reasoning as F4.2 for TOML dates. Python spells UTC as `+00:00`
        # where Go and JS write `Z`; both are valid RFC 3339, so F4.2 pins
        # `Z` and the offset is rewritten here.
        return v.isoformat().replace("+00:00", "Z")
    if isinstance(v, (bytes, bytearray)):
        import base64

        # HOCON has no binary type, so keep the base64 text (spec F5.5).
        return base64.b64encode(bytes(v)).decode("ascii")
    raise AdapterError(f"{fmt}: at {at}: unsupported value of type {type(v).__name__}")
