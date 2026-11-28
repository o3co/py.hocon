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

__all__ = ["Empty", "Substitute", "Substitutes", "View", "ViewKey"]


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
# A view's identity for memo keys and markers: (slot id, substitute id) pairs.
ViewKey = frozenset[tuple[int, int]]

_NO_MAPPINGS: ViewKey = frozenset()


class View:
    """An immutable map from document slot to substitute (§4.1). Two views are
    equal when they map the same slots to the same substitute instances,
    which is what :attr:`key` captures."""

    __slots__ = ("_m", "key")

    def __init__(self, m: dict[Slot, tuple[Substitute, Path]] | None = None) -> None:
        self._m: dict[Slot, tuple[Substitute, Path]] = m or {}
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
        return entry[0] if entry is not None else None

    def with_(self, slot: Slot, sub: Substitute) -> View:
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
    """``substitute(st, i)`` (§4.2), one instance per ``(st, i)``.

    ``fold`` is :func:`.merge.fold_entries` as used while resolving; it is
    passed in so that this module does not depend on the merge rules.
    """

    def __init__(self, fold: Callable[[Stack], Stack]) -> None:
        self._fold = fold
        # id(stack) -> (stack, {start: substitute}); the stack is kept alive so
        # its id is never reused while the cache holds it.
        self._cache: dict[int, tuple[Stack, dict[int, Substitute]]] = {}

    def get(self, st: Stack, start: int) -> Substitute:
        """The entries ``st[start:]`` as one substitute: EMPTY when there are
        none, the same instance when there is one, else their fold."""
        held = self._cache.get(id(st))
        if held is None:
            held = (st, {})
            self._cache[id(st)] = held
        by_start = held[1]
        sub = by_start.get(start)
        if sub is None:
            rest = st[start:]
            if not rest:
                sub = Empty(st[start - 1])
            elif len(rest) == 1:
                sub = rest
            else:
                sub = self._fold(rest)
            by_start[start] = sub
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
