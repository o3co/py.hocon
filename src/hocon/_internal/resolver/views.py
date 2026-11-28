"""Look-back views (xx.hocon ``docs/resolution-model.md`` §4).

A :class:`View` maps document slots to a **substitute**: the part of the slot's
stack below the entry being resolved (a stack), or :class:`Empty` when there is
nothing below. A ``${}`` written in a stack entry is resolved in a view where
its own slot shows only what is below it; that is the whole of "look-back".

Views are immutable and only ever map document slots (§3.5, §10), and
:class:`Substitutes` hands out one substitute instance per ``(stack, index)``
(§4.2), so the set of views a resolve can create is finite.
"""

from __future__ import annotations

from collections.abc import Callable

from .values import Concat, Lst, Obj, Path, Slot, Stack, Subst, Val

__all__ = ["ROOT_VIEW", "Below", "Empty", "Substitute", "Substitutes", "View", "ViewKey"]


class Empty:
    """The EMPTY substitute (§4.2): nothing below the entry ``bottom``.

    ``owned`` is the set of :class:`Subst` occurrences written inside that
    bottom entry: they are the only ones the own-path exception of §4.4
    applies to.
    """

    __slots__ = ("owned",)

    def __init__(self, bottom: Val) -> None:
        self.owned: frozenset[int] = frozenset(id(s) for s in _substs_in(bottom))


Substitute = Stack | Empty


class Below:
    """``substitute(st, start)`` (§4.2) as a handle: the entries
    ``st[start:]`` as one substitute, folded only when a lookup first reads
    them. A view maps a slot to a handle, so making a view costs nothing until
    the slot is reached; the handle's identity is the substitute's identity."""

    __slots__ = ("_fold", "_start", "_st", "_value")

    def __init__(self, st: Stack, start: int, fold: Callable[[Stack], Stack]) -> None:
        self._st = st
        self._start = start
        self._fold = fold
        self._value: Substitute | None = None

    def value(self) -> Substitute:
        """EMPTY when there are no entries, the entry itself when there is
        one, else their fold (computed once)."""
        v = self._value
        if v is None:
            rest = self._st[self._start :]
            if not rest:
                v = Empty(self._st[self._start - 1])
            elif len(rest) == 1:
                v = rest
            else:
                v = self._fold(rest)
            self._value = v
        return v


# A view's identity for memo keys and markers: (slot id, substitute id) pairs.
#
# Keys are ids, not objects, so that a key stays cheap to hash. That is safe
# only because every object whose id appears in a key outlives the resolve:
# a view maps document slots only (§3.5), which the root keeps alive, and
# every substitute handle is held by :class:`Substitutes`. A port must keep
# the same invariant (or key by the objects themselves).
ViewKey = frozenset[tuple[int, int]]

_NO_MAPPINGS: ViewKey = frozenset()


class View:
    """An immutable map from document slot to substitute (§4.1). Two views are
    equal when they map the same slots to the same substitute instances,
    which is what :attr:`key` captures."""

    __slots__ = ("_m", "key")

    def __init__(self, m: dict[Slot, tuple[Below, Path]] | None = None) -> None:
        self._m: dict[Slot, tuple[Below, Path]] = m or {}
        self.key: ViewKey = (
            frozenset((id(s), id(sub)) for s, (sub, _) in self._m.items())
            if self._m
            else _NO_MAPPINGS
        )

    def get(self, slot: Slot) -> Substitute | None:
        """The slot's substitute, or None when the view does not map it.
        A synthesized slot is never mapped (§3.5)."""
        if slot.synth or not self._m:
            return None
        entry = self._m.get(slot)
        return entry[0].value() if entry is not None else None

    def with_(self, slot: Slot, sub: Below) -> View:
        m = dict(self._m)
        m[slot] = (sub, slot.path)
        return View(m)

    def below(self, path: Path, *, strict: bool = False) -> ViewKey:
        """The mappings of slots at (or, with ``strict``, strictly) below
        ``path``: the part of the view a memo entry depends on (§5.2, §5.3)."""
        if not self._m:
            return _NO_MAPPINGS
        n = len(path)
        return frozenset(
            (id(s), id(sub))
            for s, (sub, p) in self._m.items()
            if p[:n] == path and (len(p) > n or not strict)
        )


ROOT_VIEW = View()


class Substitutes:
    """One :class:`Below` handle per ``(st, start)`` (§4.2: the same
    ``(st, i)`` always gives the same substitute instance).

    ``fold`` is :func:`.merge.fold_entries` as used while resolving; it is
    passed in so that this module does not depend on the merge rules.
    """

    def __init__(self, fold: Callable[[Stack], Stack]) -> None:
        self._fold = fold
        # id(stack) -> (stack, {start: handle}); the stack is kept alive so
        # its id is never reused while the cache holds it.
        self._cache: dict[int, tuple[Stack, dict[int, Below]]] = {}

    def get(self, st: Stack, start: int) -> Below:
        held = self._cache.get(id(st))
        if held is None:
            held = (st, {})
            self._cache[id(st)] = held
        sub = held[1].get(start)
        if sub is None:
            sub = Below(st, start, self._fold)
            held[1][start] = sub
        return sub


def _substs_in(v: Val) -> list[Subst]:
    out: list[Subst] = []
    todo: list[Val] = [v]
    while todo:
        x = todo.pop()
        if isinstance(x, Subst):
            out.append(x)
        elif isinstance(x, Concat):
            todo.extend(x.pieces)
        elif isinstance(x, Lst):
            todo.extend(x.items)
        elif isinstance(x, Obj):
            for s in x.fields.values():
                todo.extend(s.stack)
    return out
