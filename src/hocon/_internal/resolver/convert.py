"""Conversions between the resolution model's values and the public value types.

- :func:`tree_from_hocon`: a resolved :class:`~hocon.value.HoconObject` (a
  ``.properties`` include, a resolved Config handed to ``with_fallback`` /
  ``resolve_with``) as a model tree.
- :func:`to_hocon`: a resolve result as public values.
- :func:`pending_view`: an unresolved model tree as public values, each value
  that is not resolved yet replaced by a :class:`Placeholder`.

:class:`Placeholder` is the only thing of this package that reaches
``Config``: it marks "a value exists here but is not resolved".

Two facts of a resolved value have no place in the public types but still
matter when a resolved Config is merged again (``with_fallback``,
``resolve_with``): whether a string was unquoted (§1.3 rule 3 drops unquoted
whitespace after a list or an object) and whether an object ignores fallbacks
(§2.1 F2). :func:`to_hocon` records both by identity, and :func:`from_hocon`
reads them back, so a deferred merge of a resolved Config gives what one
resolve of the same text gives, as in Lightbend.
"""

from __future__ import annotations

import weakref
from typing import cast

from ...value import HoconArray, HoconObject, HoconScalar, HoconValue
from .values import Lst, Obj, Path, Scalar, Slot, Val, is_resolved

__all__ = [
    "Placeholder",
    "from_hocon",
    "pending_view",
    "same_marks",
    "to_hocon",
    "tree_from_hocon",
    "val_contains_placeholders",
]


class _Marks:
    """A set of objects by identity, holding them weakly. It never hashes or
    compares the objects themselves, so it works for any value, including a
    subclass that defines ``__eq__`` without ``__hash__``."""

    __slots__ = ("_refs",)

    def __init__(self) -> None:
        self._refs: dict[int, weakref.ref[object]] = {}

    def add(self, obj: object) -> None:
        key = id(obj)
        refs = self._refs

        def drop(ref: weakref.ref[object], key: int = key) -> None:
            if refs.get(key) is ref:
                del refs[key]

        refs[key] = weakref.ref(obj, drop)

    def __contains__(self, obj: object) -> bool:
        ref = self._refs.get(id(obj))
        return ref is not None and ref() is obj


# Public values made from an unquoted string, and from an object that ignores
# fallbacks (see the module docstring). Every code path that copies a public
# object with fields dropped goes through :func:`same_marks`.
_UNQUOTED = _Marks()
_IGNORES_FALLBACKS = _Marks()


class Placeholder:
    """An unresolved value inside a public value tree. ``value`` is the
    model value it stands for (for debugging only)."""

    __slots__ = ("value",)

    def __init__(self, value: object) -> None:
        self.value = value


def from_hocon(v: HoconValue, path: Path) -> Val:
    """A public value as a model value. A string counts as quoted, as in
    Lightbend's ``fromAnyRef`` and ``.properties`` parsing, unless a resolve
    made it from an unquoted one."""
    if isinstance(v, HoconObject):
        return tree_from_hocon(v, path)
    if isinstance(v, HoconArray):
        return Lst([from_hocon(i, path) for i in v.items])
    return Scalar(v.raw, v.value_type, v not in _UNQUOTED)


def tree_from_hocon(o: HoconObject, path: Path = ()) -> Obj:
    fields: dict[str, Slot] = {}
    for k, v in o.fields.items():
        p = (*path, k)
        fields[k] = Slot(k, [from_hocon(v, p)], p)
    return Obj(fields, o in _IGNORES_FALLBACKS)  # complete before it is frozen


def to_hocon(v: Val) -> HoconValue:
    """A resolve result as public values. Under ``allow_unresolved`` the result
    may still hold unresolved parts; each becomes a :class:`Placeholder`."""
    if isinstance(v, Scalar):
        scalar = HoconScalar(v.raw, v.value_type)
        if v.is_unquoted_string():
            _UNQUOTED.add(scalar)
        return scalar
    if isinstance(v, Lst):
        return HoconArray([to_hocon(i) for i in v.items])
    if isinstance(v, Obj):
        fields: dict[str, HoconValue] = {}
        for k, s in v.fields.items():
            fields[k] = (
                to_hocon(s.stack[0])
                if len(s.stack) == 1
                else cast("HoconValue", Placeholder(s.stack))
            )
        obj = HoconObject(fields)
        if v.flag:
            _IGNORES_FALLBACKS.add(obj)
        return obj
    return cast("HoconValue", Placeholder(v))


def same_marks(old: HoconObject, new: HoconObject) -> HoconObject:
    """``new``, a copy of ``old`` with fields dropped, keeps whether ``old``
    ignores fallbacks."""
    if old in _IGNORES_FALLBACKS:
        _IGNORES_FALLBACKS.add(new)
    return new


def pending_view(o: Obj) -> HoconObject:
    """An unresolved tree as public values: an object with a single
    assignment is walked into, a resolved value is converted, and anything
    else (a substitution, a concatenation, a field with several assignments
    left, a list holding a substitution) is a :class:`Placeholder`."""
    fields: dict[str, HoconValue] = {}
    for k, s in o.fields.items():
        if len(s.stack) == 1 and isinstance(s.stack[0], Obj):
            fields[k] = pending_view(s.stack[0])
        elif len(s.stack) == 1 and is_resolved(s.stack[0]):
            fields[k] = to_hocon(s.stack[0])
        else:
            fields[k] = cast("HoconValue", Placeholder(s.stack))
    out = HoconObject(fields)
    if o.flag:
        _IGNORES_FALLBACKS.add(out)
    return out


def val_contains_placeholders(v: object) -> bool:
    """Whether a public value tree holds a :class:`Placeholder` anywhere."""
    if isinstance(v, Placeholder):
        return True
    if isinstance(v, HoconObject):
        return any(val_contains_placeholders(x) for x in v.fields.values())
    if isinstance(v, HoconArray):
        return any(val_contains_placeholders(x) for x in v.items)
    return False
