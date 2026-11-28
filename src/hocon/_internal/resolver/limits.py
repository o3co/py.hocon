"""§10.3: limits after a cycle break (xx.hocon ``docs/resolution-model.md``,
[o3co] J6, E24).

A cycle break (an optional substitution frame catching a re-entry, other than
a substitution meeting only itself) arms the limits. They stay armed until the
outermost active substitution frame finishes: that is the break's region.
While armed, a resolve may start at most :data:`LOOKUP_LIMIT` lookups and
build at most :data:`WEIGHT_PER_VALUE` × V weight units, V being the number of
values in the document. Past either limit it fails with
:class:`~hocon.errors.ResolutionLimitError`, which no optional catches.

The resolver tells :class:`Limits` where it is (a frame starts or ends, a
break is caught, a lookup starts, a join or a lookup finishes); everything
about counting and weighing lives here.
"""

from __future__ import annotations

from ...errors import ResolutionLimitError
from .merge import is_whitespace_string
from .substituted import Substituted
from .utils import path_to_key
from .values import Concat, Lst, Obj, Scalar, Subst, Val

__all__ = ["LOOKUP_LIMIT", "WEIGHT_PER_VALUE", "Limits", "document_values"]

#: L: lookups started while armed, per resolve.
LOOKUP_LIMIT = 100_000
#: B = WEIGHT_PER_VALUE × V weight units built while armed, per resolve (no cap).
WEIGHT_PER_VALUE = 10_000

_MESSAGE = "resolution limit exceeded after a cycle break"


def document_values(root: Val) -> int:
    """V: the values of the document as §1.4 and §2 build it. A scalar, a
    substitution, a list and an object count 1 each; a list adds its items,
    an object every entry of every slot's stack (keys count nothing); a
    concatenation counts only its pieces."""
    n = 0
    todo: list[Val] = [root]
    while todo:
        v = todo.pop()
        if isinstance(v, Concat):
            todo.extend(v.pieces)
            continue
        n += 1
        if isinstance(v, Lst):
            todo.extend(v.items)
        elif isinstance(v, Obj):
            for s in v.fields.values():
                todo.extend(s.stack)
    return n


def _own_weight(v: Val) -> int:
    """1, plus 1 per 16 UTF-8 bytes of a scalar's text (its source text for a
    number, a boolean or null). Objects and lists weigh 1; keys nothing."""
    if isinstance(v, Scalar):
        return 1 + len(v.raw.encode("utf-8")) // 16
    return 1


def _join_weight(pieces: list[Val]) -> int:
    """What a join builds: a scalar's own weight, 1 plus the items of a list,
    1 for an object. Whitespace that §1.3 rule 3 drops (after a list or an
    object) counts nothing."""
    w = 0
    prev: Val | None = None
    for v in pieces:
        if isinstance(prev, (Lst, Obj)) and is_whitespace_string(v):
            continue
        if isinstance(v, Lst):
            w += 1 + len(v.items)
        else:
            w += _own_weight(v)  # a scalar's own weight; 1 for an object
        prev = v
    return w


class Limits:
    """The §10.3 state of one resolve."""

    def __init__(self, root: Obj) -> None:
        self._root = root
        self._budget: int | None = None  # B, counted the first time it is needed
        self.armed = False
        self._depth = 0  # active substitution frames (§6.1 step 3)
        self._lookups = 0
        self._weight = 0
        # Written-out weight per resolved value instance, saturated just above
        # B (each instance is weighed once); the value is held so its id stays
        # unique.
        self._weights: dict[int, tuple[int, Val]] = {}

    @property
    def budget(self) -> int:
        if self._budget is None:
            # V is a property of the document, which never changes while
            # resolving, so counting it at the first break gives the value
            # counted before resolving.
            self._budget = WEIGHT_PER_VALUE * document_values(self._root)
        return self._budget

    # ---- where the resolver is

    def frame_started(self, s: Subst) -> None:
        """A substitution reached §6.1 step 3 (not a memo hit, not active)."""
        if self.armed:
            self._lookups += 1
            if self._lookups > LOOKUP_LIMIT:
                raise self._error(
                    f"more than {LOOKUP_LIMIT} lookups (at ${{{path_to_key(s.path)}}})", s
                )
        self._depth += 1

    def frame_finished(self) -> None:
        """The frame returned or raised. The outermost one closes the region."""
        self._depth -= 1
        if self._depth == 0:
            self.armed = False

    def cycle_break(self, self_reentry: bool) -> None:
        """An optional frame caught a re-entry. A substitution meeting only
        itself (``x = ${?x}``) arms nothing."""
        if not self_reentry:
            self.armed = True

    def joined(self, pieces: list[Val], c: Concat) -> None:
        """A concatenation is about to join ``pieces`` (at least one)."""
        if self.armed:
            self._charge(_join_weight(pieces), c)

    def looked_up(self, v: Val, s: Subst) -> None:
        """An unrestricted lookup finished with ``v``."""
        if self.armed:
            self._charge(self._written_weight(v), s)

    # ---- counting

    def _charge(self, w: int, at: Subst | Concat) -> None:
        self._weight += w
        if self._weight > self.budget:
            where = (
                f"${{{path_to_key(at.path)}}}"
                if isinstance(at, Subst)
                else f"concatenation in {path_to_key(at.fpath)}"
            )
            raise self._error(f"more than {self.budget} weight units built (at {where})", at)

    def _written_weight(self, root: Val) -> int:
        """The written-out weight of a resolved value: a part shared in
        several places counts once per place. Computed without recursion,
        once per instance, saturated at B + 1."""
        cap = self.budget + 1
        done = self._weights
        todo: list[tuple[Val, bool]] = [(_unwrap(root), False)]
        while todo:
            v, children_done = todo.pop()
            if id(v) in done:
                continue
            parts = _parts(v)
            if not children_done:
                todo.append((v, True))
                todo.extend((_unwrap(p), False) for p in parts if id(_unwrap(p)) not in done)
                continue
            w = _own_weight(v)
            for p in parts:
                w += done[id(_unwrap(p))][0]
                if w >= cap:
                    w = cap
                    break
            done[id(v)] = (w, v)
        return done[id(_unwrap(root))][0]

    def _error(self, detail: str, at: Subst | Concat) -> ResolutionLimitError:
        key = path_to_key(at.path) if isinstance(at, Subst) else path_to_key(at.fpath)
        return ResolutionLimitError(f"{_MESSAGE}: {detail}", key, at.line, at.col)


def _unwrap(v: Val) -> Val:
    """§5.5 only clears flags: a substituted object weighs what its base does."""
    while isinstance(v, Substituted):
        v = v.base
    return v


def _parts(v: Val) -> list[Val]:
    if isinstance(v, Lst):
        return v.items
    if isinstance(v, Obj):
        return [x for s in v.fields.values() for x in s.stack]
    return []
