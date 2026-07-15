"""Java-properties parsing for ``.properties`` includes.

Mirrors ts.hocon ``src/internal/properties/properties.ts``. Multi-line + Unicode
escapes are a documented simplification (S23.5, S23.6). Object always wins over
scalar on a key conflict (S23.4, HOCON.md L1485), enforced via key-sorted
insertion so conflict direction is input-order independent.
"""

from __future__ import annotations

from typing import Any

from ...value import HoconObject, HoconScalar, HoconValue

__all__ = ["parse_properties", "properties_to_hocon_value"]

_DANGEROUS_KEYS = frozenset(("__proto__", "constructor", "prototype"))


def parse_properties(input_text: str) -> dict[str, Any]:
    root: dict[str, Any] = {}

    pairs: list[tuple[str, str]] = []
    for line in input_text.split("\n"):
        trimmed = line.strip()
        if trimmed == "" or trimmed.startswith("#") or trimmed.startswith("!"):
            continue
        sep_idx = _find_separator(trimmed)
        if sep_idx == -1:
            continue
        key = trimmed[:sep_idx].strip()
        value = trimmed[sep_idx + 1 :].strip()
        if key == "":
            continue
        pairs.append((key, value))

    # Sort by key so conflict-direction is input-order independent (S23.4).
    pairs.sort(key=lambda kv: kv[0])

    for key, value in pairs:
        _set_nested(root, key.split("."), value)

    return root


def _find_separator(line: str) -> int:
    for i, ch in enumerate(line):
        if ch == "=" or ch == ":":
            return i
    return -1


def _set_nested(obj: dict[str, Any], segments: list[str], value: str) -> None:
    current = obj
    for seg in segments[:-1]:
        if seg in _DANGEROUS_KEYS:
            return
        existing = current.get(seg)
        if not isinstance(existing, dict):
            current[seg] = {}
        current = current[seg]
    last = segments[-1]
    if last in _DANGEROUS_KEYS:
        return
    # S23.4 — object always wins over scalar: do not overwrite an object.
    if isinstance(current.get(last), dict):
        return
    current[last] = value


def properties_to_hocon_value(input_text: str) -> HoconValue:
    """Convert a ``.properties`` string to a HoconValue (object with string
    scalars). All values remain strings — no type coercion."""
    return _record_to_hocon_value(parse_properties(input_text))


def _record_to_hocon_value(obj: dict[str, Any]) -> HoconObject:
    fields: dict[str, HoconValue] = {}
    for key, val in obj.items():
        if isinstance(val, str):
            fields[key] = HoconScalar(val, "string")
        elif isinstance(val, dict):
            fields[key] = _record_to_hocon_value(val)
    return HoconObject(fields)
