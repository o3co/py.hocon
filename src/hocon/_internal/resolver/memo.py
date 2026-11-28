"""The resolve memo (xx.hocon ``docs/resolution-model.md`` §5).

Three tables, all per resolve and none keyed by path (§5.3 "never cache by
path"):

- ``subst``: :class:`Subst` occurrence -> result of its unrestricted resolution
  (§5.1), with the view it was computed in;
- ``concat``: (:class:`Concat`, mappings strictly below its field) -> result
  (§5.2);
- ``stack``: (slot, stack in the view, mappings at or below the slot,
  restriction) -> result of the stack walk (§5.3).

Abandoned work (§5.4) is discarded by rolling back to a :meth:`Memo.mark`:
every write records its key in a journal, so a rollback costs only the
entries written since the mark.
"""

from __future__ import annotations

from collections.abc import Hashable
from typing import Any

from .values import Path, Result, Slot, Stack, Subst, Val
from .views import View, ViewKey

__all__ = ["Memo", "StackKey"]

# (slot, id(stack), view mappings at or below the slot, restriction)
StackKey = tuple[Slot, int, ViewKey, Path | None]


class Memo:
    def __init__(self) -> None:
        # id(subst) -> (subst, result, view the result was computed in)
        self._subst: dict[int, tuple[Subst, Result, View]] = {}
        # (id(concat), mappings) -> (concat, result)
        self._concat: dict[tuple[int, ViewKey], tuple[Val, Val]] = {}
        # StackKey -> (result, stack); the stack is held so its id stays unique
        self._stack: dict[StackKey, tuple[Val, Stack]] = {}
        self._journal: list[tuple[dict[Any, Any], Hashable]] = []

    # ---- §5.4 rollback

    def mark(self) -> int:
        return len(self._journal)

    def rollback(self, mark: int) -> None:
        """Discard every entry written since ``mark``."""
        while len(self._journal) > mark:
            table, key = self._journal.pop()
            table.pop(key, None)

    def _write(self, table: dict[Any, Any], key: Hashable, value: object) -> None:
        if key not in table:
            self._journal.append((table, key))
        table[key] = value

    # ---- §5.1 substitutions

    def subst(self, s: Subst) -> tuple[Result, View] | None:
        hit = self._subst.get(id(s))
        return (hit[1], hit[2]) if hit is not None else None

    def has_subst(self, s: Subst) -> bool:
        return id(s) in self._subst

    def put_subst(self, s: Subst, result: Result, view: View) -> None:
        self._write(self._subst, id(s), (s, result, view))

    # ---- §5.2 concatenations

    def concat(self, key: tuple[int, ViewKey]) -> Val | None:
        hit = self._concat.get(key)
        return hit[1] if hit is not None else None

    def put_concat(self, key: tuple[int, ViewKey], c: Val, result: Val) -> None:
        self._write(self._concat, key, (c, result))

    # ---- §5.3 stacks

    def stack(self, key: StackKey) -> Val | None:
        hit = self._stack.get(key)
        return hit[0] if hit is not None else None

    def put_stack(self, key: StackKey, st: Stack, result: Val) -> None:
        self._write(self._stack, key, (result, st))
