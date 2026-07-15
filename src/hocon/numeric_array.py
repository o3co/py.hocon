"""S15 — numerically-indexed object → array conversion helper.

Mirrors ts.hocon ``src/value/numeric-array.ts``. Private helper shared between
the accessor call site (``Config.get_list``) and the resolver concat call site
(``SubstitutionResolver._resolve_concat``); not part of the public API.
"""

from __future__ import annotations

import re

from .value import HoconObject, HoconValue

__all__ = ["numeric_object_to_array"]

# Canonical decimal non-negative integers only.
# Rejects: "+1", "-0", "-1", "00", "01", " 1", "1 ", "0x1", "1e2", "1.0", "".
_CANONICAL_INT = re.compile(r"(?:0|[1-9][0-9]*)")


def numeric_object_to_array(value: HoconValue) -> list[HoconValue] | None:
    """Attempt to convert a numerically-keyed HOCON object to an array.

    - not an object              → None
    - empty object               → None  (S15.4: empty NOT converted)
    - no key parses as non-neg int → None
    - otherwise                  → values sorted by parsed key (ascending)

    Conversion is non-recursive: only top-level keys are examined. A new list is
    returned; the original object is not mutated.
    """
    if not isinstance(value, HoconObject):
        return None
    if len(value.fields) == 0:
        return None

    eligible: list[tuple[int, HoconValue]] = []
    for key, val in value.fields.items():
        if not _CANONICAL_INT.fullmatch(key):
            continue
        n = int(key)
        # i32 max: 2147483647
        if n > 2_147_483_647:
            continue
        eligible.append((n, val))

    if not eligible:
        return None

    eligible.sort(key=lambda e: e[0])
    return [e[1] for e in eligible]
