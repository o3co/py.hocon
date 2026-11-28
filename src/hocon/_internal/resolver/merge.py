"""The two ways values combine (xx.hocon ``docs/resolution-model.md``).

- :func:`fallback` (§2.1) puts one stack on top of another. Repeated
  assignment, dotted paths, includes, the stack walk (§3.2 W5), object
  concatenation and ``with_fallback`` (§8.3) all use it. While resolving, an
  object merge is the lazy :class:`Overlay` of §10.2; at parse time (and in
  ``with_fallback``) it is a plain merged :class:`.values.Obj`.
- :func:`join` / :func:`consolidate` (§1.3) join the pieces of a value
  concatenation, at parse time (§1.4) and when a concatenation resolves.

They never mutate their inputs (except :func:`merge_included`, which adds to
the object being built, and the private lists of :func:`fold_into`), and they
keep slot identity wherever the spec says a slot is kept.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterator

from ...errors import ResolveError
from .values import (
    Concat,
    Lst,
    Obj,
    Path,
    Scalar,
    Slot,
    Stack,
    Subst,
    Unresolved,
    Val,
    carries_stack,
    field_resolved,
    is_resolved,
    stack_ignores_fallbacks,
)

__all__ = [
    "Overlay",
    "consolidate",
    "fallback",
    "fold_entries",
    "fold_into",
    "is_whitespace_string",
    "join",
    "merge_included",
]


def fallback(
    top: Stack, existing: Stack | None, *, synth: bool, receiver_first: bool = False
) -> Stack:
    """§2.1 ``fallback(top, existing)``: the first rule that matches.

    ``synth`` is True while resolving: an object merge is then an
    :class:`Overlay` (§10.2) whose merged keys are synthesized slots (§3.5).
    ``receiver_first`` is the key order of ``with_fallback`` (§8.3): the top's
    keys first at every level merged by the call. Otherwise the order is the
    parse-time document order (the existing keys first).
    """
    if existing is None:  # F1
        return top
    if stack_ignores_fallbacks(top):  # F2: everything below is dropped, never evaluated
        return top
    if len(top) > 1:  # F3
        return top + existing
    t = top[0]
    if len(existing) > 1 or isinstance(existing[0], (Subst, Concat)):  # F4
        return [t, *existing]
    e = existing[0]
    if isinstance(t, Obj) and isinstance(e, Obj):  # F5
        if synth:
            return [Overlay([t, e])]
        return [_merge_obj(t, e, receiver_first)]
    if isinstance(t, Obj):  # F6 (t is not flagged here: F2 caught that)
        if is_resolved(t):
            return [_flagged(t)]
        return [t, *existing]
    return [t, *existing]  # F7


def _flagged(t: Obj) -> Obj:
    """``t`` with the flag set (F6)."""
    if isinstance(t, Overlay):
        return Overlay(list(t.layers), True)
    return Obj(t.fields, True, frozen=t.frozen)


def fold_into(st: Stack, nxt: Stack) -> Stack:
    """``fallback(st, nxt)`` for a private list ``st`` (§10.2): F3 / F4
    extend it in place."""
    if stack_ignores_fallbacks(st):
        return st
    if (
        len(st) > 1
        or len(nxt) > 1
        or isinstance(nxt[0], (Subst, Concat))
        or isinstance(st[0], (Subst, Concat))
    ):
        st.extend(nxt)
        return st
    return list(fallback(st, nxt, synth=True))


def fold_entries(entries: Stack) -> Stack:
    """The left fold ``m := [e0]; m := fallback(m, [e])`` over ``entries``
    (§4.2 substitute), extending ``m`` in place (§10.2)."""
    m: Stack = [entries[0]]
    for v in entries[1:]:
        if stack_ignores_fallbacks(m):  # F2: nothing below is kept
            break
        if len(m) > 1 or isinstance(m[0], (Subst, Concat)):  # F3 / F4
            m.append(v)
        else:
            m = list(fallback(m, [v], synth=True))
    return m


def _merge_obj(t: Obj, e: Obj, receiver_first: bool) -> Obj:
    """``merge(t, e)`` at parse time or in ``with_fallback``: a key in both
    gets a new slot holding ``fallback(t.k, e.k)``; a key in one keeps that
    same slot, and so does a key whose top stack ignores fallbacks (F2 returns
    it unchanged). The flag is ``e``'s. The result is not frozen yet: the
    builder (or ``with_fallback``) freezes the finished tree."""
    out: dict[str, Slot] = {}
    first, second = (t, e) if receiver_first else (e, t)
    for k, s in first.fields.items():
        other = second.fields.get(k)
        if other is None:
            out[k] = s
            continue
        ts, es = (s, other) if receiver_first else (other, s)
        stack = fallback(ts.stack, es.stack, synth=False, receiver_first=receiver_first)
        out[k] = ts if stack is ts.stack else Slot(k, stack, es.path)
    for k, s in second.fields.items():
        if k not in out:
            out[k] = s
    return Obj(out, e.flag, frozen=False)


class Overlay(Obj):
    """§10.2 lazy merge of objects built while resolving: ``layers``, top
    first, merged with the §2.1 rules only on demand.

    :meth:`get_field` folds one key's stacks top-down and stops at the first
    stack that ignores fallbacks (F2). A key that one layer alone supplies
    keeps that layer's slot; any other key is a synthesized slot (§3.5). The
    key set and :attr:`fields` are built only when the object is iterated.
    The flag is the bottom layer's (F5), unless set (F6).
    """

    __slots__ = ("_cache", "_set_flag", "layers")

    def __init__(self, layers: list[Obj], flag: bool | None = None) -> None:
        super().__init__(None)
        self._fields = None  # built on first iteration
        self.layers = layers
        self._set_flag = flag
        self._cache: dict[str, Slot | None] = {}

    @property
    def flag(self) -> bool:
        return self.layers[-1].flag if self._set_flag is None else self._set_flag

    def append(self, layer: Obj) -> None:
        """Add a bottom layer. Only while the walk that made this overlay
        still owns it (§3.2 W5: one overlay per walk)."""
        self.layers.append(layer)
        self._cache = {}
        self._fields = None
        self._res = self._car = None

    def push_top(self, layer: Obj) -> None:
        """Add a top layer. Only while the concatenation that made this
        overlay still owns it (``consolidate``)."""
        self.layers.insert(0, layer)
        self._cache = {}
        self._fields = None
        self._res = self._car = None

    def get_field(self, k: str) -> Slot | None:
        if self._fields is not None:
            return self._fields.get(k)
        if k in self._cache:
            return self._cache[k]
        first: Slot | None = None
        st: Stack = []
        owned = False
        for layer in self.layers:
            f = layer.get_field(k)
            if f is None:
                continue
            if first is None:
                first, st = f, f.stack
            else:
                if not owned:
                    st, owned = list(st), True
                st = fold_into(st, f.stack)
            if stack_ignores_fallbacks(st):
                break
        r = None if first is None else first if not owned else Slot(k, st, first.path, True)
        self._cache[k] = r
        return r

    def field_keys(self) -> list[str]:
        """Bottom layer first, so existing keys keep their position (F5)."""
        if self._fields is not None:
            return list(self._fields)
        out: list[str] = []
        seen: set[str] = set()
        done: set[int] = set()

        def walk(o: Obj) -> None:
            if id(o) in done:
                return
            done.add(id(o))
            # An overlay whose fields are built already gives the same keys,
            # in the same order, as walking its layers again (the model walks
            # them again; only the cost differs: layers skipped as done have
            # all their keys seen already).
            if isinstance(o, Overlay) and o._fields is None:
                for layer in reversed(o.layers):
                    walk(layer)
            else:
                for k in o.fields:  # built once per object and kept
                    if k not in seen:
                        seen.add(k)
                        out.append(k)

        walk(self)
        return out

    @property
    def fields(self) -> dict[str, Slot]:
        if self._fields is None:
            fields: dict[str, Slot] = {}
            for k in self.field_keys():
                s = self.get_field(k)
                assert s is not None
                fields[k] = s
            self._fields = fields
        return self._fields

    def unresolved_keys(self) -> Iterator[str]:
        """§10.2 item 5: a key resolved in every layer that has it is
        resolved in the merge (F2 / F5 / F6 keep it so), so only the keys
        some layer has unresolved are merged and looked at. A resolved layer
        has nothing to give, and a layer met twice (an object merged with
        itself) is looked at once, so a nested overlay is never walked twice."""
        seen: set[str] = set()
        met: set[int] = set()
        for layer in self.layers:
            if id(layer) in met or layer.is_resolved():
                continue
            met.add(id(layer))
            for k in layer.unresolved_keys():
                if k in seen:
                    continue
                seen.add(k)
                s = self.get_field(k)
                if s is not None and not field_resolved(s):
                    yield k

    def is_resolved(self) -> bool:
        if self._res is None:
            self._res = all(layer.is_resolved() for layer in self.layers) or (
                next(self.unresolved_keys(), None) is None
            )
        return self._res

    def carries(self) -> bool:
        # Exact: the fold itself can flag a child (F6), so look at the merged
        # fields rather than at the layers.
        if self._car is None:
            self._car = self.flag or any(carries_stack(s.stack) for s in self.fields.values())
        return self._car


def merge_included(obj: Obj, included: Obj, path: Path) -> None:
    """§2.2 include: each key of the included root, in its order, goes on top
    of the including object's stack for that key; new keys are appended."""
    for k, s in included.fields.items():
        existing = obj.fields.get(k)
        if existing is not None:
            existing.stack = fallback(s.stack, existing.stack, synth=False)
        else:
            obj.fields[k] = Slot(k, s.stack, (*path, k))


# ---------------------------------------------------------------- §1.3 join

_CANONICAL_INT = re.compile(r"(?:0|[1-9][0-9]*)")
_I32_MAX = 2_147_483_647
_I32_DIGITS = len(str(_I32_MAX))
# Java Character.isWhitespace beyond the Unicode separators Zs / Zl / Zp.
_JAVA_WS = frozenset("\t\n\x0b\f\r\x1c\x1d\x1e\x1f")


def _is_whitespace(c: str) -> bool:
    """Lightbend's ``ConfigImplUtil.isWhitespace``: a Java whitespace
    character, or U+00A0, U+2007, U+202F, U+FEFF (§1.3 rule 3)."""
    return c in _JAVA_WS or c == "﻿" or unicodedata.category(c) in ("Zs", "Zl", "Zp")


def is_whitespace_string(v: Val) -> bool:
    """An unquoted string of whitespace only: what §1.3 rule 3 drops after a
    list or an object."""
    return (
        isinstance(v, Scalar)
        and v.is_unquoted_string()
        and all(_is_whitespace(c) for c in v.raw)
    )


def _numeric_obj_to_list(o: Obj) -> Lst | None:
    """S15.3–S15.5 numeric-key conversion of a resolved object: the values of
    the canonical non-negative integer keys, in key order. None when no key is
    eligible (an empty object included)."""
    eligible: list[tuple[int, Val]] = []
    for k, s in o.fields.items():
        # The length check comes first: int() refuses very long digit strings.
        if len(k) <= _I32_DIGITS and _CANONICAL_INT.fullmatch(k) and int(k) <= _I32_MAX:
            eligible.append((int(k), s.stack[0]))
    if not eligible:
        return None
    eligible.sort(key=lambda kv: kv[0])
    return Lst([v for _, v in eligible])


def _kind(v: Val) -> str:
    if isinstance(v, Obj):
        return "object"
    if isinstance(v, Lst):
        return "array"
    return "scalar"


def join(
    builder: list[Val],
    right: Val,
    *,
    at_parse: bool,
    line: int = 0,
    col: int = 0,
) -> None:
    """§1.3: join the last built piece with ``right``, in place.

    ``at_parse`` is True for the parse-time consolidation of §1.4. A side that
    is still a substitution (or an unresolved object that would need the list
    conversion) is then left as a separate piece, and the concatenation joins
    it once resolved.
    """
    left = builder[-1]
    if isinstance(left, (Subst, Concat, Unresolved)) or isinstance(
        right, (Subst, Concat, Unresolved)
    ):
        builder.append(right)  # not joinable yet: kept as its own piece
        return
    # Rule 0: an object next to a list is first converted to a list.
    if isinstance(left, Obj) and isinstance(right, Lst):
        if not is_resolved(left):
            builder.append(right)
            return
        converted = _numeric_obj_to_list(left)
        if converted is None:
            raise _same_kind_error(left, right, line, col)
        left = converted
    elif isinstance(left, Lst) and isinstance(right, Obj):
        if not is_resolved(right):
            builder.append(right)
            return
        converted = _numeric_obj_to_list(right)
        if converted is None:
            raise _same_kind_error(left, right, line, col)
        right = converted
    if isinstance(left, Obj) and isinstance(right, Obj):  # rule 1: the right piece on top
        st = fallback([right], [left], synth=not at_parse)
        builder[-1] = st[0]
        return
    if isinstance(left, Lst) and isinstance(right, Lst):  # rule 2
        builder[-1] = Lst(left.items + right.items)
        return
    # Rule 3: only unquoted whitespace after a list or an object is dropped,
    # at parse time and when resolving alike (E5; Lightbend 1.4.10). Any other
    # text there falls through to rule 4, a type error.
    if isinstance(left, (Lst, Obj)) and is_whitespace_string(right):
        return
    # Rule 4: both are rendered to strings and joined.
    if not isinstance(left, Scalar) or not isinstance(right, Scalar):
        raise _string_concat_error(left, right, line, col)
    builder[-1] = Scalar(left.raw + right.raw, "string", True)


def _string_concat_error(left: Val, right: Val, line: int, col: int) -> ResolveError:
    return ResolveError(
        f"cannot concatenate {_kind(left)} with {_kind(right)}: arrays and objects "
        f"may not appear in string value concatenation (S10.13)",
        "",
        line,
        col,
    )


def _same_kind_error(left: Val, right: Val, line: int, col: int) -> ResolveError:
    return ResolveError(
        f"cannot concatenate {_kind(left)} with {_kind(right)}: value concatenation "
        "requires same-kind operands (S10.4)",
        "",
        line,
        col,
    )


def consolidate(
    pieces: list[Val], *, at_parse: bool, line: int = 0, col: int = 0
) -> list[Val]:
    """§1.3 / §1.4: join ``pieces`` left to right (nested concatenations are
    flattened first). One value remains unless a piece is still unresolved."""
    out: list[Val] = []
    own: Overlay | None = None  # an overlay this call made (resolve time)
    for p in pieces:
        if isinstance(p, Concat):
            flat = p.pieces
        elif isinstance(p, Unresolved) and p.pieces is not None:
            flat = p.pieces  # a partial concatenation substituted in
        else:
            flat = [p]
        for q in flat:
            if not out:
                out.append(q)
            elif own is not None and out[-1] is own and isinstance(q, Obj) and not q.flag:
                # Rule 1 again on an overlay this call built: put the right
                # piece on top of the same overlay instead of nesting one
                # overlay per piece (§10.2), so a long `${a} ${b} ${c} …`
                # does not nest the interpreter's stack.
                own.push_top(q)
            else:
                left = out[-1]
                join(out, q, at_parse=at_parse, line=line, col=col)
                made = out[-1]
                if made is not left:  # unchanged (whitespace dropped): still ours
                    # Only an overlay join just built (not an operand) is ours.
                    fresh = made is not q
                    own = made if not at_parse and isinstance(made, Overlay) and fresh else None
    return out
