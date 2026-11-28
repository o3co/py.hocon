"""Conversions between the resolution model's values and the public value types.

- :func:`tree_from_hocon`: a resolved :class:`~hocon.value.HoconObject` (a
  ``.properties`` include, a resolved Config handed to ``with_fallback`` /
  ``resolve_with``) as a model tree.
- :func:`to_hocon`: a resolve result as public values.
- :func:`pending_view`: an unresolved model tree as public values, each value
  that is not resolved yet replaced by a :class:`Placeholder`.

:class:`Placeholder` is the only thing of this package that reaches
``Config``: it marks "a value exists here but is not resolved".
"""

from __future__ import annotations

from typing import cast

from ...value import HoconArray, HoconObject, HoconScalar, HoconValue
from .values import Lst, Obj, Path, Scalar, Slot, Val, is_resolved

__all__ = [
    "Placeholder",
    "from_hocon",
    "pending_view",
    "to_hocon",
    "tree_from_hocon",
    "val_contains_placeholders",
]


class Placeholder:
    """An unresolved value inside a public value tree. ``value`` is the
    model value it stands for (for debugging only)."""

    __slots__ = ("value",)

    def __init__(self, value: object) -> None:
        self.value = value


def from_hocon(v: HoconValue, path: Path) -> Val:
    """A public value as a model value. Strings count as quoted, as in
    Lightbend's ``fromAnyRef`` and ``.properties`` parsing."""
    if isinstance(v, HoconObject):
        return tree_from_hocon(v, path)
    if isinstance(v, HoconArray):
        return Lst([from_hocon(i, path) for i in v.items])
    return Scalar(v.raw, v.value_type, True)


def tree_from_hocon(o: HoconObject, path: Path = ()) -> Obj:
    out = Obj()
    for k, v in o.fields.items():
        p = (*path, k)
        out.fields[k] = Slot(k, [from_hocon(v, p)], p)
    return out


def to_hocon(v: Val) -> HoconValue:
    """A resolve result as public values. Under ``allow_unresolved`` the result
    may still hold unresolved parts; each becomes a :class:`Placeholder`."""
    if isinstance(v, Scalar):
        return HoconScalar(v.raw, v.value_type)
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
        return HoconObject(fields)
    return cast("HoconValue", Placeholder(v))


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
    return HoconObject(fields)


def val_contains_placeholders(v: object) -> bool:
    """Whether a public value tree holds a :class:`Placeholder` anywhere."""
    if isinstance(v, Placeholder):
        return True
    if isinstance(v, HoconObject):
        return any(val_contains_placeholders(x) for x in v.fields.values())
    if isinstance(v, HoconArray):
        return any(val_contains_placeholders(x) for x in v.items)
    return False
