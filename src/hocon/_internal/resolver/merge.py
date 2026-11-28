"""The two ways values combine (xx.hocon ``docs/resolution-model.md``).

- :func:`fallback` (§2.1) puts one stack on top of another. Repeated
  assignment, dotted paths, includes, the stack walk (§3.2 W5), object
  concatenation and ``with_fallback`` (§8.3) all use it.
- :func:`join` / :func:`consolidate` (§1.3) join the pieces of a value
  concatenation, at parse time (§1.4) and when a concatenation resolves.

Both are pure: they never mutate their inputs, and they keep slot identity
wherever the spec says a slot is kept.
"""

from __future__ import annotations

import re

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
    Val,
    Whitespace,
    is_resolved,
    stack_ignores_fallbacks,
)

__all__ = ["consolidate", "fallback", "fold_entries", "join", "merge_included"]


def fallback(
    top: Stack, existing: Stack | None, *, synth: bool, receiver_first: bool = False
) -> Stack:
    """§2.1 ``fallback(top, existing)``: the first rule that matches.

    ``synth`` marks the slots a merge creates as synthesized (§3.5): True
    while resolving, False at parse time and in ``with_fallback``.
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
        return [_merge_obj(t, e, synth, receiver_first)]
    if isinstance(t, Obj):  # F6 (t is not flagged here: F2 caught that)
        if is_resolved(t):
            return [Obj(dict(t.fields), True)]
        return [t, *existing]
    return [t, *existing]  # F7


def fold_entries(entries: Stack, *, synth: bool) -> Stack:
    """The left fold ``m := [e0]; m := fallback(m, [e])`` over ``entries``
    (§4.2 substitute). F2 and F3 are taken inline, so a long stack of
    substitutions folds in linear time instead of copying ``m`` per entry."""
    m: Stack = [entries[0]]
    for v in entries[1:]:
        if stack_ignores_fallbacks(m):  # F2: nothing below can change m
            break
        if len(m) > 1:  # F3: m ++ [v]; m is always a list made here
            m.append(v)
        else:
            m = fallback(m, [v], synth=synth)
    return m


def _merge_obj(t: Obj, e: Obj, synth: bool, receiver_first: bool) -> Obj:
    """``merge(t, e)``: a key in both gets a new slot holding
    ``fallback(t.k, e.k)``; a key in one keeps that same slot. The flag is
    ``e``'s."""
    out: dict[str, Slot] = {}
    first, second = (t, e) if receiver_first else (e, t)
    for k, s in first.fields.items():
        other = second.fields.get(k)
        if other is None:
            out[k] = s
            continue
        ts, es = (s, other) if receiver_first else (other, s)
        stack = fallback(ts.stack, es.stack, synth=synth, receiver_first=receiver_first)
        out[k] = Slot(k, stack, es.path, synth)
    for k, s in second.fields.items():
        if k not in out:
            out[k] = s
    return Obj(out, e.flag)


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
    if isinstance(left, (Subst, Concat)) or isinstance(right, (Subst, Concat)):
        builder.append(right)
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
    # Rule 3: an unquoted string after a list or an object is dropped.
    if isinstance(left, (Lst, Obj)) and isinstance(right, Scalar) and right.is_unquoted_string():
        if at_parse and not isinstance(right, Whitespace):
            # E5 (o3co): unquoted text written right after an object or a
            # list literal (`a = { b: 1 } x`, fixture ce05) is a type error,
            # where Lightbend drops it. Rule 3 applies to whitespace, and to
            # everything joined once substitutions are resolved
            # (`[1] ${x}` with `x = s`, zig-hocon 051; `${a}x`, rv084).
            raise _string_concat_error(left, right, line, col)
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
    for p in pieces:
        for q in p.pieces if isinstance(p, Concat) else [p]:
            if not out:
                out.append(q)
            else:
                join(out, q, at_parse=at_parse, line=line, col=col)
    return out
