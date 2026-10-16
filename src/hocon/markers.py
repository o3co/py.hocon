"""Typing markers that read HOCON unit values in typed decoding.

``Annotated[int, Bytes()]`` reads a byte size (``64KiB``),
``Annotated[float, Duration("s")]`` a duration (``30m``) and
``Annotated[Period, PeriodUnit()]`` a period (``2w``) with the same rules as
:meth:`Config.get_bytes` / :meth:`Config.get_duration` /
:meth:`Config.get_period`: all read through the ``read_*`` functions in
:mod:`hocon.coerce`. A marker owns only the HOCON unit syntax; constraints
(integer, range, …) stay in the annotated type and any further metadata.

``require_unit=True`` on any marker refuses a value that does not name its
unit — a number (``ttl = 30``) or a string of the number alone (``"30"``, what
an environment variable gives) — which would otherwise read in the default
unit (ms, bytes, days). The value is read first, so one that does not read
keeps its own error; whether a unit is named is decided by the reader's own
split (:func:`hocon.coerce.names_magnitude_unit` /
:func:`hocon.coerce.names_period_unit`). The getters have no such option.

A marker acts only on the values :meth:`Config.decode` reads from a config,
in both decode paths:

- dataclasses and the other hints ``decode`` builds itself, where the marker
  reads the scalar's source text exactly like the getter;
- Pydantic v2 models, via ``__get_pydantic_core_schema__`` (pydantic is only
  imported when Pydantic itself asks for the schema). ``decode`` marks its
  ``model_validate`` call with a validation context, and the marker reads a
  value only under it. Any other validation — constructing a model, a
  ``default_factory``, ``model_validate(model.model_dump())``, JSON — sees the
  field as its plain type, so values are not converted twice. A default
  validated with ``validate_default=True`` is part of decode's validation and
  is read as a HOCON value. A model that overrides ``__init__`` does not
  receive the validation context (a Pydantic limitation), so markers inside
  it do not act.
  Pydantic receives plain values, so a number is read through its value
  rather than its source text. That gives the same result (``1e3`` is 1000
  in every path) except for an unquoted number with more significant digits
  than a float holds, which Pydantic sees already rounded, and an unquoted
  ``-0``, which Pydantic sees as ``0``.
"""

from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import timedelta
from decimal import Decimal
from types import UnionType
from typing import Annotated, Any, ClassVar, Union, get_args, get_origin

from .coerce import (
    UNIT_BYTE_SIZE,
    UNIT_DURATION,
    UNIT_PERIOD,
    ByteUnit,
    DurationUnit,
    UnitReadError,
    is_byte_unit,
    is_duration_unit,
    names_magnitude_unit,
    names_period_unit,
    read_bytes,
    read_duration,
    read_period,
    read_timedelta,
)
from .config import Period

__all__ = ["Bytes", "Duration", "PeriodUnit"]

# The Pydantic validation context Config.decode passes to model_validate; the
# markers' validators read HOCON values only under it.
PYDANTIC_CONTEXT_KEY = "hocon.decode"
# True while a marker builds the schema it wraps: a second marker on the same
# type would otherwise read the first one's output as a raw unit value.
_BUILDING: ContextVar[bool] = ContextVar("hocon_marker_building", default=False)


class _UnitMarker:
    """Base of the unit markers; ``decode`` recognises any instance. Not part
    of the public API — subclass at your own risk."""

    what: ClassVar[str]
    targets: ClassVar[tuple[type, ...]]
    require_unit: bool  # a keyword-only dataclass field on each marker

    def to_target(self, raw: str, target: type) -> object:
        """Read ``raw`` for a ``target`` from :meth:`resolve_target`. Raises
        ``UnitReadError``."""
        raise NotImplementedError

    def names_unit(self, raw: str) -> bool:
        """Whether ``raw`` names its unit, as this marker's reader splits it."""
        raise NotImplementedError

    def read_scalar(self, raw: str, target: type, *, number: bool) -> object:
        """Read a scalar's text for ``target``; ``number`` says the scalar is a
        number, which never names a unit. The reader runs first, so a value
        that does not read keeps its own error; then ``require_unit`` refuses
        one that names no unit. Raises ``UnitReadError``."""
        value = self.to_target(raw, target)
        if self.require_unit and (number or not self.names_unit(raw)):
            raise UnitReadError(self.what, "missing-unit", raw)
        return value

    def resolve_target(self, target: Any) -> type:
        """The concrete type this marker decodes into, with ``Optional`` and
        nested ``Annotated`` unwrapped. Raises ``TypeError`` for a type the
        marker cannot produce."""
        inner = _concrete(target)
        if not (isinstance(inner, type) and inner in self.targets):
            names = " / ".join(t.__name__ for t in self.targets)
            raise TypeError(f"{self!r} decodes into {names}, not {target!r}")
        return inner

    def __get_pydantic_core_schema__(self, source_type: Any, handler: Any) -> Any:
        from pydantic_core import core_schema

        if _BUILDING.get():
            raise TypeError(f"nested unit markers on one type (inner: {source_type!r})")
        target = self.resolve_target(source_type)

        def validate(value: object, info: Any) -> object:
            context = info.context
            if not (isinstance(context, dict) and context.get(PYDANTIC_CONTEXT_KEY)):
                return value  # not a value Config.decode read from a config
            if value is None or isinstance(value, (timedelta, Period)):
                return value  # Optional's None, or a validate_default timedelta / Period
            raw = _raw_of(value, self.what)  # str, int or float past this point
            return self.read_scalar(raw, target, number=not isinstance(value, str))

        token = _BUILDING.set(True)
        try:
            inner_schema = handler(source_type)
        finally:
            _BUILDING.reset(token)
        return core_schema.with_info_before_validator_function(validate, inner_schema)


class _MagnitudeMarker(_UnitMarker):
    """A marker that reads a number in an output unit (duration, byte size)."""

    def read(self, raw: str) -> float:
        """The value in this marker's unit. Raises ``UnitReadError``."""
        raise NotImplementedError

    def to_target(self, raw: str, target: type) -> int | float | timedelta:
        """A whole result comes back as ``int`` so an ``int`` target needs no
        rounding; a fractional one stays ``float`` and the target type decides."""
        n = self.read(raw)
        return int(n) if float(n).is_integer() else n

    def names_unit(self, raw: str) -> bool:
        return names_magnitude_unit(raw)


@dataclass(frozen=True)
class Bytes(_MagnitudeMarker):
    """Read a HOCON byte size (``64KiB``) in ``unit`` (default bytes), with
    :meth:`Config.get_bytes`' rules. Annotate ``int`` or ``float``.

    ``unit`` is an output-unit token (``B`` / ``KB`` / ``KiB`` / ``MB`` /
    ``MiB`` / ``GB`` / ``GiB`` / ``TB`` / ``TiB``), not a config spelling:
    ``Bytes("kB")`` raises ``ValueError``. ``require_unit=True`` refuses a
    value that does not name its unit (``1024``, ``"1024"``), which would
    otherwise read as bytes."""

    unit: ByteUnit = "B"
    require_unit: bool = field(default=False, kw_only=True)

    what: ClassVar[str] = UNIT_BYTE_SIZE
    targets: ClassVar[tuple[type, ...]] = (int, float)

    def __post_init__(self) -> None:
        if not is_byte_unit(self.unit):
            raise ValueError(f"unknown byte unit {self.unit!r}")

    def read(self, raw: str) -> float:
        return read_bytes(raw, self.unit)


@dataclass(frozen=True)
class Duration(_MagnitudeMarker):
    """Read a HOCON duration (``30m``) with :meth:`Config.get_duration`' rules.
    Annotate ``int`` / ``float`` for a number in ``unit`` (default ms), or
    ``timedelta`` (``unit`` then has no effect).

    ``unit`` is an output-unit token (``ns`` / ``us`` / ``ms`` / ``s`` / ``m``
    / ``h`` / ``d``), not a config spelling: ``Duration("seconds")`` raises
    ``ValueError``. ``require_unit=True`` refuses a value that does not name
    its unit (``30``, ``"30"``), which would otherwise read as milliseconds."""

    unit: DurationUnit = "ms"
    require_unit: bool = field(default=False, kw_only=True)

    what: ClassVar[str] = UNIT_DURATION
    targets: ClassVar[tuple[type, ...]] = (int, float, timedelta)

    def __post_init__(self) -> None:
        if not is_duration_unit(self.unit):
            raise ValueError(f"unknown duration unit {self.unit!r}")

    def read(self, raw: str) -> float:
        return read_duration(raw, self.unit)

    def to_target(self, raw: str, target: type) -> int | float | timedelta:
        if target is timedelta:
            return read_timedelta(raw)
        return super().to_target(raw, target)


@dataclass(frozen=True)
class PeriodUnit(_UnitMarker):
    """Read a HOCON period (``2w``) with :meth:`Config.get_period`' rules.
    Annotate :class:`~hocon.Period`.

    A plain ``Period`` field already reads a period in a dataclass; the marker
    is how a Pydantic model reads one, and how either asks for the unit:
    ``require_unit=True`` refuses a value that does not name its unit (``7``,
    ``"7"``), which would otherwise read as days."""

    require_unit: bool = field(default=False, kw_only=True)

    what: ClassVar[str] = UNIT_PERIOD
    targets: ClassVar[tuple[type, ...]] = (Period,)

    def to_target(self, raw: str, target: type) -> Period:
        return Period(*read_period(raw))

    def names_unit(self, raw: str) -> bool:
        return names_period_unit(raw)


def _markers_in(target: Any) -> list[_UnitMarker]:
    """Every unit marker on ``target``, through ``Optional`` and nested
    ``Annotated`` (the same layers :func:`_concrete` peels)."""
    found: list[_UnitMarker] = []
    while True:
        origin = get_origin(target)
        if origin is Annotated:
            base, *metadata = get_args(target)
            found += [m for m in metadata if isinstance(m, _UnitMarker)]
            target = base
        elif origin is Union or origin is UnionType:
            non_none = [a for a in get_args(target) if a is not type(None)]
            if len(non_none) != 1:
                return found
            target = non_none[0]
        else:
            return found


def _concrete(target: Any) -> Any:
    """``target`` with ``Optional[...]`` and ``Annotated[...]`` peeled off."""
    while True:
        origin = get_origin(target)
        if origin is Annotated:
            target = get_args(target)[0]
        elif origin is Union or origin is UnionType:
            non_none = [a for a in get_args(target) if a is not type(None)]
            if len(non_none) != 1:
                return target
            target = non_none[0]
        else:
            return target


def _raw_of(value: object, what: str) -> str:
    """The text a plain (Pydantic-side) value reads as. A float is written out
    from its shortest repr in positional form (``1e-07`` → ``0.0000001``); the
    reader accepts exponents too, so this only keeps the text canonical."""
    if isinstance(value, str):
        return value
    if isinstance(value, bool):
        raise ValueError(f"expected {what}, got boolean")
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return format(Decimal(repr(value)), "f")
    raise ValueError(f"expected {what}, got {type(value).__name__}")
