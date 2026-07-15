"""Typed coercions for Config accessors: numbers, booleans, durations, byte sizes.

Mirrors ts.hocon ``src/coerce.ts``. Duration unit names are case-sensitive
(S19.8, HOCON.md L1304). Single-letter byte abbreviations are powers of two
(S21.4, HOCON.md L1385).

Standalone module: it must not import :mod:`hocon.value` (value imports this).
"""

from __future__ import annotations

import math
import re

__all__ = [
    "DECIMAL_NUMBER_RE",
    "ByteUnit",
    "DurationUnit",
    "coerce_boolean",
    "coerce_number",
    "parse_bytes",
    "parse_duration",
    "parse_period",
]

DECIMAL_NUMBER_RE = re.compile(r"-?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?")

# HOCON_WS = Java Character.isWhitespace set
#          ∪ { 0x00A0 NBSP, 0x2007 FIGURE SPACE, 0x202F NARROW NO-BREAK SPACE }
#          ∪ { 0xFEFF BOM }
# Do NOT use str.strip() — it strips NEL (U+0085) and other Unicode space
# separators that HOCON does not classify as whitespace. Mirrors
# ``isHoconWhitespace`` in lexer.py byte-for-byte.


def _is_hocon_ws(cp: int) -> bool:
    if cp in (0x09, 0x0A, 0x0B, 0x0C, 0x0D):
        return True
    if 0x1C <= cp <= 0x1F:
        return True
    if cp in (0x20, 0xA0, 0xFEFF):
        return True
    if cp == 0x1680:
        return True
    if 0x2000 <= cp <= 0x200A:
        return True
    if cp in (0x2028, 0x2029, 0x202F, 0x205F):
        return True
    if cp == 0x3000:
        return True
    return False


def _trim_hocon_ws(s: str) -> str:
    start = 0
    end = len(s)
    while start < end and _is_hocon_ws(ord(s[start])):
        start += 1
    while end > start and _is_hocon_ws(ord(s[end - 1])):
        end -= 1
    return s[start:end]


_TRUTHY = frozenset(("true", "yes", "on"))
_FALSY = frozenset(("false", "no", "off"))


def coerce_boolean(value: str) -> bool | None:
    lower = value.lower()
    if lower in _TRUTHY:
        return True
    if lower in _FALSY:
        return False
    return None


def coerce_number(value: str) -> float | int | None:
    if not DECIMAL_NUMBER_RE.fullmatch(value):
        return None
    if any(c in value for c in ".eE"):
        return float(value)
    return int(value)


DurationUnit = str  # 'ns' | 'us' | 'ms' | 's' | 'm' | 'h' | 'd'

_DURATION_UNITS: dict[str, float] = {
    "ns": 1e-6, "nanosecond": 1e-6, "nanoseconds": 1e-6,
    "us": 1e-3, "microsecond": 1e-3, "microseconds": 1e-3,
    "ms": 1, "millisecond": 1, "milliseconds": 1,
    "s": 1_000, "second": 1_000, "seconds": 1_000,
    "m": 60_000, "minute": 60_000, "minutes": 60_000,
    "h": 3_600_000, "hour": 3_600_000, "hours": 3_600_000,
    "d": 86_400_000, "day": 86_400_000, "days": 86_400_000,
}

_OUTPUT_DURATION_UNITS: dict[str, float] = {
    "ns": 1e-6, "us": 1e-3, "ms": 1, "s": 1_000, "m": 60_000, "h": 3_600_000, "d": 86_400_000,
}


def _leading_numeric_prefix_len(trimmed: str) -> int:
    i = 0
    while i < len(trimmed):
        ch = trimmed[i]
        if i == 0 and (ch == "-" or ch == "+"):
            i += 1
            continue
        if ch != "." and not ("0" <= ch <= "9"):
            break
        i += 1
    return i


def parse_duration(value: str, output_unit: DurationUnit | None = None) -> float:
    unit_out = output_unit if output_unit is not None else "ms"
    trimmed = _trim_hocon_ws(value)
    i = _leading_numeric_prefix_len(trimmed)
    if i == 0:
        return math.nan
    try:
        num = float(trimmed[:i])
    except ValueError:
        return math.nan
    if math.isnan(num):
        return math.nan
    # S19.8 — unit match is case-sensitive per HOCON.md L1304 (lowercase only).
    unit = _trim_hocon_ws(trimmed[i:])
    divisor = _OUTPUT_DURATION_UNITS.get(unit_out)
    if divisor is None:
        return math.nan
    # S18.1 + S18.4: bare number (no unit) → treat as default unit (ms).
    if unit == "":
        return num / divisor
    mult = _DURATION_UNITS.get(unit)
    if mult is None:
        return math.nan
    ms = num * mult
    return ms / divisor


# S20 — Period format. Values are bounded to i32 like Lightbend
# (`Integer.parseInt`) and rs.hocon's `Period { i32, i32, i32 }`, so a period
# that would overflow there is invalid here too, not silently widened.
_I32_MIN = -(2**31)
_I32_MAX = 2**31 - 1


def parse_period(value: str) -> tuple[int, int, int] | None:
    """Parse a HOCON period string into a ``(years, months, days)`` tuple.

    Accepts ``[ws] integer [ws] [unit] [ws]``; a bare number is taken as days
    (S20.1, HOCON.md L1321). Unit names are case-sensitive lowercase (the
    S19.8 duration rule applies to periods too, HOCON.md L1304). Period is
    integer-only per Lightbend ``Integer.parseInt`` — fractional strings like
    ``"7.5"`` return None (up03), unlike duration/bytes which accept them.
    """
    trimmed = _trim_hocon_ws(value)
    if not trimmed:
        return None
    i = 0
    while i < len(trimmed) and (("0" <= trimmed[i] <= "9") or trimmed[i] in "+-"):
        i += 1
    num_str = trimmed[:i]
    unit = _trim_hocon_ws(trimmed[i:])
    if not num_str:
        return None
    try:
        n = int(num_str)
    except ValueError:
        return None
    if not _I32_MIN <= n <= _I32_MAX:
        return None
    if unit == "" or unit in ("d", "day", "days"):
        return (0, 0, n)
    if unit in ("w", "week", "weeks"):
        days = n * 7
        if not _I32_MIN <= days <= _I32_MAX:
            return None
        return (0, 0, days)
    if unit in ("m", "mo", "month", "months"):
        return (0, n, 0)
    if unit in ("y", "year", "years"):
        return (n, 0, 0)
    return None


ByteUnit = str  # 'B' | 'KB' | 'KiB' | 'MB' | 'MiB' | 'GB' | 'GiB' | 'TB' | 'TiB'

_BYTE_UNITS: dict[str, float] = {
    "B": 1, "byte": 1, "bytes": 1,
    "KB": 1_000, "kilobyte": 1_000, "kilobytes": 1_000,
    "KiB": 1_024, "kibibyte": 1_024, "kibibytes": 1_024,
    "MB": 1_000_000, "megabyte": 1_000_000, "megabytes": 1_000_000,
    "MiB": 1_048_576, "mebibyte": 1_048_576, "mebibytes": 1_048_576,
    "GB": 1_000_000_000, "gigabyte": 1_000_000_000, "gigabytes": 1_000_000_000,
    "GiB": 1_073_741_824, "gibibyte": 1_073_741_824, "gibibytes": 1_073_741_824,
    "TB": 1_000_000_000_000, "terabyte": 1_000_000_000_000, "terabytes": 1_000_000_000_000,
    "TiB": 1_099_511_627_776, "tebibyte": 1_099_511_627_776, "tebibytes": 1_099_511_627_776,
    # S21.4 — single-letter abbreviations → powers of two (java -Xmx convention).
    "K": 1_024, "k": 1_024,
    "M": 1_024 ** 2, "m": 1_024 ** 2,
    "G": 1_024 ** 3, "g": 1_024 ** 3,
    "T": 1_024 ** 4, "t": 1_024 ** 4,
    "P": 1_024 ** 5, "p": 1_024 ** 5,
    "E": 1_024 ** 6, "e": 1_024 ** 6,
    # lowercase short-form aliases
    "b": 1,
    "kb": 1_000, "kib": 1_024,
    "mb": 1_000_000, "mib": 1_048_576,
    "gb": 1_000_000_000, "gib": 1_073_741_824,
    "tb": 1_000_000_000_000, "tib": 1_099_511_627_776,
}

_OUTPUT_BYTE_UNITS: dict[str, float] = {
    "B": 1, "KB": 1_000, "KiB": 1_024, "MB": 1_000_000, "MiB": 1_048_576,
    "GB": 1_000_000_000, "GiB": 1_073_741_824, "TB": 1_000_000_000_000, "TiB": 1_099_511_627_776,
}

# JS Number.MAX_SAFE_INTEGER = 2^53 - 1. Kept for parity with the ts.hocon
# overflow guard even though Python ints are unbounded.
_MAX_SAFE_INTEGER = 2 ** 53 - 1


def parse_bytes(value: str, output_unit: ByteUnit | None = None) -> float:
    unit_out = output_unit if output_unit is not None else "B"
    trimmed = _trim_hocon_ws(value)
    i = _leading_numeric_prefix_len(trimmed)
    if i == 0:
        return math.nan
    try:
        num = float(trimmed[:i])
    except ValueError:
        return math.nan
    if math.isnan(num):
        return math.nan
    unit = _trim_hocon_ws(trimmed[i:])
    divisor = _OUTPUT_BYTE_UNITS.get(unit_out)
    if divisor is None:
        return math.nan
    # S18.1 + S18.4: bare number (no unit) → truncate toward zero (Lightbend
    # BigDecimal.toBigInteger) and treat as default unit (bytes).
    if unit == "":
        num_bytes = math.trunc(num)
        if abs(num_bytes) > _MAX_SAFE_INTEGER:
            raise OverflowError("byte size overflows representable range (max 2^53-1 bytes)")
        return num_bytes / divisor
    mult = _BYTE_UNITS.get(unit)
    if mult is None:
        mult = _BYTE_UNITS.get(unit.lower())
    if mult is None:
        return math.nan
    num_bytes_f = num * mult
    if abs(num_bytes_f) > _MAX_SAFE_INTEGER:
        raise OverflowError("byte size overflows representable range (max 2^53-1 bytes)")
    result = num_bytes_f / divisor
    return round(result) if unit_out == "B" else result
