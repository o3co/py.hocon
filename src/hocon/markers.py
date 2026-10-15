"""Typing markers that read HOCON unit values in typed decoding.

``Annotated[int, Bytes()]`` reads a byte size (``64KiB``) and
``Annotated[float, Duration("s")]`` reads a duration (``30m``) with the same
rules as :meth:`Config.get_bytes` / :meth:`Config.get_duration`: both read
through the ``read_*`` functions in :mod:`hocon.coerce`. A marker owns only the
HOCON unit syntax; constraints (integer, range, …) stay in the annotated type
and any further metadata.

The markers work in both decode paths:

- dataclasses and the other hints :meth:`Config.decode` builds itself, where
  the marker reads the scalar's source text exactly like the getter;
- Pydantic v2 models, via ``__get_pydantic_core_schema__`` (pydantic is only
  imported when Pydantic itself asks for the schema). Pydantic receives plain
  values, so a number is read through its value rather than its source text:
  a bare number in exponent form (``1e3``) reads as ``1000`` there, while the
  getters and dataclass decoding reject it as an unknown unit ``e3``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from types import UnionType
from typing import Any, ClassVar, Union, get_args, get_origin

from .coerce import (
    ByteUnit,
    DurationUnit,
    UnitReadError,
    is_byte_unit,
    is_duration_unit,
    read_bytes,
    read_duration,
)

__all__ = ["Bytes", "Duration", "UnitMarker"]


class UnitMarker:
    """Base of the unit markers. ``decode`` recognises any instance."""

    what: ClassVar[str]
    targets: ClassVar[tuple[type, ...]]

    def read(self, raw: str) -> float:
        """The value in this marker's unit. Raises :class:`UnitReadError`."""
        raise NotImplementedError

    def to_target(self, raw: str, target: type) -> int | float | timedelta:
        """Read ``raw`` for a ``target`` from :meth:`resolve_target`. A whole
        result comes back as ``int`` so an ``int`` target needs no rounding;
        a fractional one stays ``float`` and the target type decides."""
        n = self.read(raw)
        return int(n) if float(n).is_integer() else n

    def resolve_target(self, target: Any) -> type:
        """The concrete type this marker decodes into, with ``Optional``
        stripped. Raises ``TypeError`` for a type the marker cannot produce."""
        inner = _strip_optional(target)
        if not (isinstance(inner, type) and inner in self.targets):
            names = " / ".join(t.__name__ for t in self.targets)
            raise TypeError(f"{self!r} decodes into {names}, not {target!r}")
        return inner

    def __get_pydantic_core_schema__(self, source_type: Any, handler: Any) -> Any:
        from pydantic_core import core_schema

        target = self.resolve_target(source_type)

        def validate(value: object) -> object:
            if value is None or isinstance(value, timedelta):
                return value  # Optional's None, or an already-built value
            return self.to_target(_raw_of(value, self.what), target)

        return core_schema.no_info_before_validator_function(validate, handler(source_type))


@dataclass(frozen=True)
class Bytes(UnitMarker):
    """Read a HOCON byte size (``64KiB``) in ``unit`` (default bytes), with
    :meth:`Config.get_bytes`' rules. Annotate ``int`` or ``float``."""

    unit: ByteUnit = "B"

    what: ClassVar[str] = "byte size"
    targets: ClassVar[tuple[type, ...]] = (int, float)

    def __post_init__(self) -> None:
        if not is_byte_unit(self.unit):
            raise ValueError(f"unknown byte unit {self.unit!r}")

    def read(self, raw: str) -> float:
        return read_bytes(raw, self.unit)


@dataclass(frozen=True)
class Duration(UnitMarker):
    """Read a HOCON duration (``30m``) with :meth:`Config.get_duration`' rules.
    Annotate ``int`` / ``float`` for a number in ``unit`` (default ms), or
    ``timedelta`` (``unit`` then has no effect)."""

    unit: DurationUnit = "ms"

    what: ClassVar[str] = "duration"
    targets: ClassVar[tuple[type, ...]] = (int, float, timedelta)

    def __post_init__(self) -> None:
        if not is_duration_unit(self.unit):
            raise ValueError(f"unknown duration unit {self.unit!r}")

    def read(self, raw: str) -> float:
        return read_duration(raw, self.unit)

    def to_target(self, raw: str, target: type) -> int | float | timedelta:
        if target is timedelta:
            return timedelta(milliseconds=read_duration(raw))
        return super().to_target(raw, target)


def _strip_optional(target: Any) -> Any:
    origin = get_origin(target)
    if origin is Union or origin is UnionType:
        non_none = [a for a in get_args(target) if a is not type(None)]
        if len(non_none) == 1:
            return non_none[0]
    return target


def _raw_of(value: object, what: str) -> str:
    """The text a plain (Pydantic-side) value reads as. A float is written out
    positionally (``1e-07`` → ``0.0000001``) so the reader sees digits only."""
    if isinstance(value, str):
        return value
    if isinstance(value, int) and not isinstance(value, bool):
        return str(value)
    if isinstance(value, float):
        return format(Decimal(repr(value)), "f")
    raise UnitReadError(what, "invalid", repr(value))
