"""Phase 2: resolve the model tree, top down and lazily.

xx.hocon ``docs/resolution-model.md`` §3 (walking stacks, lookup, restricted
resolution), §6 (cycles, with the interim rule of §6.3) and §7.2 (lookup order
and the environment). Views are in :mod:`.views`, the memo in :mod:`.memo`,
and the merge rules in :mod:`.merge`; this module only decides *where* each of
them is consulted and *what* is done with the answer.

A ``${}`` is resolved only when a value is taken out: the root object is
resolved field by field (§3.1), and a substitution resolves only the ancestors
on its path, each restricted to the next key (§3.3, §3.4).
"""

from __future__ import annotations

from typing import Literal

from ...errors import ResolveError
from .memo import Memo
from .merge import Overlay, consolidate, fallback, fold_entries
from .substituted import Substituted
from .types import ResolveOptions
from .utils import path_to_key
from .values import (
    MISSING,
    Concat,
    Lst,
    Missing,
    Obj,
    Partial,
    Patch,
    Path,
    Result,
    Scalar,
    Slot,
    Stack,
    Subst,
    Unresolved,
    Val,
    has_path,
    is_resolved,
    stack_ignores_fallbacks,
)
from .views import ROOT_VIEW, Empty, Substitute, Substitutes, View, ViewKey

__all__ = ["SubstitutionResolver"]

# Safety valve, not part of the resolution model: once a cycle has been broken
# (§6.3), a resolve may run at most this many further lookups. A dense web of
# optional cycles (k keys each reading all k, written twice) makes the number
# of look-back views, and so of lookups, grow faster than exponentially in k;
# the reference model and Lightbend take minutes or more at k = 6. A document
# without a cycle break is never limited. This replaces the post-cut work
# budget of py.hocon#68, pending a §10 decision in xx.hocon
# docs/resolution-model.md (the other implementations need the same bound).
POST_CUT_LOOKUP_LIMIT = 100_000
# The same for size. After a cycle break, the result may weigh at most this
# many units per value of the document, and never more than the cap: a node
# weighs 1, plus 1 per 16 characters of scalar or key text. A ring of optional
# references whose value doubles on every lap (`a_i = ${?a_j}${?a_j}x`, or an
# object holding two references to the next key, written twice) otherwise
# grows until memory runs out (Lightbend: OutOfMemoryError). The numbers are
# py.hocon#68's, which match rs and go.
POST_CUT_VALUE_PER_SOURCE_NODE = 10_000
POST_CUT_VALUE_CAP = 2_000_000


class _ReEntry(Exception):
    """§6.2: a re-entry, caught by the innermost active substitution frame
    (§6.3). ``kind`` is ``"marker"`` for an active ``(Subst, View)`` needed
    again (case a) and ``"empty"`` for a lookup that reached EMPTY (case b)."""

    def __init__(self, kind: Literal["marker", "empty"]) -> None:
        super().__init__(kind)
        self.kind = kind


class SubstitutionResolver:
    def __init__(self, root: Obj, opts: ResolveOptions) -> None:
        self.root = root
        self.opts = opts
        self.memo = Memo()
        self.substitutes = Substitutes(fold_entries)
        # §3.5: a merged leaf rebuilt by another lookup is the same stack,
        # interned by its entry instances (this also keeps them alive).
        self.interned: dict[tuple[int, ...], Stack] = {}
        # §5.5: one Substituted per (value, substitution), holding both.
        self.substituted: dict[tuple[int, int], tuple[Substituted, Obj]] = {}
        # §6.1: the active (Subst, View) pairs.
        self.active: set[tuple[int, ViewKey]] = set()
        # Lookups run since the first cycle break (POST_CUT_LOOKUP_LIMIT), and
        # the weight the result may reach once there was one.
        self.post_cut_lookups: int | None = None
        self.value_budget = 0
        self.use_env = opts.use_system_environment is not False
        self.allow_unresolved = bool(opts.allow_unresolved)

    def resolve(self) -> Val:
        """§3.1: the root object, resolved in the root view."""
        result = self._resolve_obj(self.root, ROOT_VIEW, None)
        if self.post_cut_lookups is not None:
            self._check_size(result)
        return result

    def _check_size(self, result: Obj) -> None:
        """After a cycle break, the result written out may not weigh more than
        the value budget. Resolved values are shared, so a ring of optional
        references can make a small result expand exponentially when it is
        written out. The count stops as soon as the budget is spent."""
        budget = self.value_budget
        for sl in result.fields.values():
            todo: list[Val] = list(sl.stack)
            while todo:
                v = todo.pop()
                budget -= _weight(v)
                if isinstance(v, Lst):
                    todo.extend(v.items)
                elif isinstance(v, Obj):
                    for child in v.fields.values():
                        todo.extend(child.stack)
                if budget < 0:
                    raise ResolveError(
                        f"resolved value too large: {path_to_key(sl.path)} keeps growing "
                        "(a cycle through optional substitutions?)",
                        path_to_key(sl.path),
                        0,
                        0,
                    )

    # ---------------------------------------------------------- §3.2 stacks

    def _stack_of(self, slot: Slot, view: View) -> Substitute:
        """§4.1: a slot's stack is its substitute when the view maps it."""
        sub = view.get(slot)
        return slot.stack if sub is None else sub

    # The functions below call each other once per nesting level and per
    # substitution link, so the hot path is kept to few Python frames: the walk
    # is part of _value_of, entries are dispatched directly, and the lookup is
    # part of _resolve_subst. That keeps the depth a document can reach close
    # to what the parser itself allows.

    def _value_of(self, slot: Slot, view: View, restrict: Path | None) -> Result:
        """§3.2 ``valueOf(slot, view, restrict)``, with the stack memo of §5.3.
        The caller has checked that the slot is not EMPTY in the view."""
        st = self._stack_of(slot, view)
        assert not isinstance(st, Empty)
        below = view.below(slot.path)
        full = self.memo.stack((slot, id(st), below, None))
        if full is not None:
            if restrict is None:
                return full
            # A full result answers a restricted request, except for presence:
            # a path the full result lacks (at any depth) is decided by the
            # restricted walk, on the raw value (J2).
            if has_path(full, restrict):
                return full
        key = (slot, id(st), below, restrict)
        if restrict is not None:
            hit = self.memo.stack(key)
            if hit is not None:
                return hit
        # The walk (W1–W5): the entries top first, each folded under the
        # result so far, until the result ignores fallbacks.
        if slot.synth and len(st) > 1:
            st = self.interned.setdefault(tuple(id(x) for x in st), st)
        merged: Stack | None = None
        own: Overlay | None = None  # the walk's own merge overlay (§10.2)
        r: Result
        for i, e in enumerate(st):
            if merged is not None and stack_ignores_fallbacks(merged):  # W1 cut
                break
            if isinstance(e, (Subst, Concat)):
                # W3 look-back: below this entry, the slot shows the rest of its
                # stack (a merged leaf by its path and entries, §3.5). A single
                # entry makes no view.
                inner = view
                if len(st) > 1:
                    inner = view.with_(slot, self.substitutes.get(st, i + 1))
                if isinstance(e, Subst):
                    r = self._resolve_subst(e, inner, restrict)
                else:
                    r = self._resolve_concat(e, inner)
            elif merged is not None and _shadowed(merged, e):  # W2 shadow skip
                continue
            elif isinstance(e, Obj):  # W4 forward
                r = self._resolve_obj(e, view, restrict)
            else:
                r = self._resolve(e, view, restrict)
            if isinstance(r, Missing):  # W5: a missing entry contributes nothing
                continue
            if isinstance(r, Unresolved):  # allow_unresolved: the field stays unresolved
                return r
            rs: Stack = r.stack if isinstance(r, Partial) else [r]
            if merged is None:
                merged = rs
            elif (
                len(merged) == 1
                and len(rs) == 1
                and isinstance(merged[0], Obj)
                and isinstance(rs[0], Obj)
                and not merged[0].flag
            ):
                # F5 object over object: one overlay per walk, extended in place.
                if merged[0] is not own:
                    own = Overlay([merged[0]])
                    merged = [own]
                own.append(rs[0])
            else:
                merged = fallback(merged, rs, synth=True)
        if merged is None:
            return MISSING
        result = merged[0] if len(merged) == 1 else Partial(merged)
        self.memo.put_stack(key, st, result)
        return result

    # ---------------------------------------------------------- §3.4 / §3.6 values

    def _resolve(self, v: Val, view: View, restrict: Path | None) -> Result:
        if isinstance(v, Scalar):
            return v
        if isinstance(v, Lst):
            if restrict is not None:  # §3.4: a list is returned unchanged
                return v
            items: list[Val] = []
            for item in v.items:
                r = self._resolve(item, view, None)
                if not isinstance(r, Missing):  # §7.3: a missing item is dropped
                    items.append(r)
            return Lst(items)
        if isinstance(v, Obj):
            return self._resolve_obj(v, view, restrict)
        if isinstance(v, Subst):
            return self._resolve_subst(v, view, restrict)
        if isinstance(v, Concat):
            return self._resolve_concat(v, view)
        raise ResolveError(f"internal: cannot resolve {type(v).__name__}", "", 0, 0)

    def _resolve_obj(self, o: Obj, view: View, restrict: Path | None) -> Obj:
        if restrict is None:
            # §3.6: every key in order; an EMPTY slot is absent (§4.3), a
            # missing value is omitted.
            out: dict[str, Slot] = {}
            for k, s in o.fields.items():
                if isinstance(self._stack_of(s, view), Empty):
                    continue
                r = self._value_of(s, view, None)
                if not isinstance(r, Missing):
                    out[k] = Slot(k, [r], s.path)
            return Obj(out, o.flag)
        # §3.4: only key k changes, as a patch of the original (§10.2). An
        # EMPTY slot stays, so that find reaches it.
        k, rest = restrict[0], restrict[1:]
        child = o.get_field(k)
        if child is None:
            return o
        st = self._stack_of(child, view)
        if isinstance(st, Empty):
            return o
        if not rest:
            # The leaf stays raw. If the view maps it, it carries the mapped
            # stack but is still the same document slot (its origin), so a
            # merge sees the look-back and a further look-back advances it.
            if st is child.stack:
                return o
            return Patch(o, k, Slot(k, st, child.path, False, child.origin))
        r = self._value_of(child, view, rest)
        if isinstance(r, Missing):
            return Patch(o, k, None)
        return Patch(o, k, Slot(k, r.stack if isinstance(r, Partial) else [r], child.path, True))

    def _resolve_concat(self, c: Concat, view: View) -> Result:
        """§1.3 with the concatenation memo of §5.2. Pieces resolve
        unrestricted, even under a restriction (§3.4)."""
        key = (id(c), view.below(c.fpath, strict=True))
        hit = self.memo.concat(key)
        if hit is not None:
            return hit
        resolved: list[Val] = []
        unresolved: Unresolved | None = None
        for p in c.pieces:
            if isinstance(p, Subst):
                r = self._resolve_subst(p, view, None)
            else:
                r = self._resolve(p, view, None)
            if isinstance(r, Missing):  # §1.3: an omitted optional piece
                continue
            if isinstance(r, Unresolved):
                # allow_unresolved: the concatenation stays unresolved, but the
                # other pieces are still resolved, so a cycle in them aborts.
                unresolved = unresolved or r
                continue
            resolved.append(r)
        if unresolved is not None:
            return unresolved
        result: Result = MISSING  # every piece omitted
        if resolved:
            # After a cycle break, check the joined size before joining: a
            # string or a list is at most as large as its pieces together.
            if (
                self.post_cut_lookups is not None
                and sum(_weight(r) for r in resolved) > self.value_budget
            ):
                raise ResolveError(
                    f"resolved value too large: {path_to_key(c.fpath)} keeps growing "
                    "(a cycle through optional substitutions?)",
                    path_to_key(c.fpath),
                    c.line,
                    c.col,
                )
            joined = consolidate(resolved, at_parse=False, line=c.line, col=c.col)
            if len(joined) != 1:
                if self.allow_unresolved:
                    # An unresolved object next to a list cannot be joined
                    # yet. A type mismatch already known still raised above.
                    return Unresolved(c)
                raise ResolveError("internal: concatenation did not join", "", c.line, c.col)
            result = joined[0]
        hit = self.memo.concat(key)  # first completed result wins
        if hit is not None:
            return hit
        if not isinstance(result, Missing):  # MISSING is not stored
            self.memo.put_concat(key, c, result)
        return result

    @staticmethod
    def _child(v: Val, key: str, path: Path) -> Slot | None:
        """§3.4 ``child(v, key)``: descend one key of an object, or of the
        object layers on top of a partial stack (§11 J1)."""
        if isinstance(v, Obj):
            return v.get_field(key)
        if isinstance(v, Partial):
            parts: list[Stack] = []
            for layer in v.stack:
                if not isinstance(layer, Obj):
                    break
                s = layer.get_field(key)
                if s is not None:
                    parts.append(s.stack)
            if not parts:
                return None
            st = parts[0]
            for p in parts[1:]:
                st = fallback(st, p, synth=True)
            return Slot(key, st, path, True)
        return None

    # ---------------------------------------------------------- §3.3 lookup

    def _find(self, path: Path, view: View, s: Subst) -> tuple[Slot | None, bool]:
        """``find(path, view)``: the leaf slot, or None. The flag is True when
        the walk reached an EMPTY slot that counts as a re-entry (§4.4)."""
        first = self.root.get_field(path[0])
        if first is None:
            return None, False
        slot = first
        for j in range(len(path)):
            st = self._stack_of(slot, view)
            if isinstance(st, Empty):
                # §4.4 own-path exception: the slot's own reference, written in
                # the bottom entry, is simply not found.
                if s.path == slot.path and id(s) in st.owned:
                    return None, False
                return None, True
            if j == len(path) - 1:
                return slot, False
            # Only the ancestors are resolved, each restricted to the rest.
            v = self._value_of(slot, view, path[j + 1 :])
            if isinstance(v, Missing):
                return None, False
            nxt = self._child(v, path[j + 1], (*slot.path, path[j + 1]))
            if nxt is None:
                return None, False
            slot = nxt
        return slot, False

    # ---------------------------------------------------------- §6 substitutions

    def _resolve_subst(self, s: Subst, view: View, restrict: Path | None) -> Result:
        """§6.1 (with the substitution memo of §5.1) around the lookup of §7.2."""
        hit = self.memo.subst(s)
        if hit is not None:
            result, computed_in = hit
            if not (restrict and isinstance(result, Obj) and not has_path(result, restrict)):
                return result
            # §5.3 presence: decided by a restricted resolution in the view
            # that produced the memoized result.
            view = computed_in
        # §6.1: only document-slot mappings make a marker fresh (§3.5).
        marker = (id(s), view.slot_key)
        if marker in self.active:
            raise _ReEntry("marker")  # §6.2 (a)
        if self.post_cut_lookups is not None:
            self.post_cut_lookups += 1
            if self.post_cut_lookups > POST_CUT_LOOKUP_LIMIT:
                raise self._error(s, "substitution cycle too complex to resolve")
        self.active.add(marker)
        mark = self.memo.mark()
        cycle_break = False
        r: Result
        try:
            # §7.2 steps 1–2: the full path, then (only if not found) the
            # path as written in an included file.
            slot, reached_empty = self._find(s.path, view, s)
            if slot is None and s.prefix_len > 0:
                slot, reached_empty2 = self._find(s.path[s.prefix_len :], view, s)
                reached_empty = reached_empty or reached_empty2
            # §5.4: what find memoized is kept if the leaf's resolution re-enters.
            mark = self.memo.mark()
            if slot is None:
                env = self._from_env(s)  # step 3
                if env is not None:
                    r = env
                elif reached_empty:
                    raise _ReEntry("empty")  # §6.2 (b)
                else:
                    r = self._undefined(s)  # step 4
            else:
                # The leaf resolves under the caller's restriction (§3.3). Found
                # means present: a found leaf that is MISSING never falls back
                # to the original path or the environment (#123).
                r = self._value_of(slot, view, restrict)
                if isinstance(r, Obj):
                    r = self._substituted(r, s)
                if isinstance(r, Missing) and not s.optional:
                    if not self.allow_unresolved:
                        raise self._error(s, "could not resolve substitution")
                    r = Unresolved(s)
        except _ReEntry as e:
            # §6.3 [interim]: the innermost active frame catches. Work done
            # since the frame's mark is abandoned (§5.4).
            self.memo.rollback(mark)
            if self.post_cut_lookups is None:
                self.post_cut_lookups = 0
                self.value_budget = min(
                    _source_nodes(self.root) * POST_CUT_VALUE_PER_SOURCE_NODE, POST_CUT_VALUE_CAP
                )
            if not s.optional:
                raise self._error(s, "circular substitution", "is part of a cycle") from None
            r = MISSING
            cycle_break = e.kind == "marker"
        finally:
            self.active.discard(marker)
        if restrict is None or isinstance(r, Missing) or is_resolved(r):
            if self.memo.has_subst(s):  # first completed result wins
                if restrict is None:
                    stored = self.memo.subst(s)
                    assert stored is not None
                    return stored[0]
                return r
            # MISSING is remembered only when it broke a cycle (§5.1).
            if not isinstance(r, Missing) or cycle_break:
                self.memo.put_subst(s, r, view)
        return r

    def _substituted(self, r: Obj, s: Subst) -> Substituted:
        """§5.5, once per (value, substitution): a rebuilt merged leaf then
        has the same entries (§3.5)."""
        if isinstance(r, Substituted):
            return r  # already rewritten (see Substituted)
        key = (id(r), id(s))
        held = self.substituted.get(key)
        if held is None:
            held = (Substituted(r, s, s.path), r)
            self.substituted[key] = held
        return held[0]

    def _from_env(self, s: Subst) -> Val | None:
        """§7.2 step 3 (E17): the full dotted path first, then the original."""
        if not self.use_env:
            return None
        names = [".".join(s.path)]
        if s.prefix_len > 0:
            names.append(".".join(s.path[s.prefix_len :]))
        env = self.opts.env
        if s.list_suffix:
            # S13c: NAME_0, NAME_1, … as a list; the first name whose _0 is
            # set wins entirely.
            for base in names:
                if f"{base}_0" not in env:
                    continue
                items: list[Val] = []
                i = 0
                while f"{base}_{i}" in env:
                    items.append(Scalar(env[f"{base}_{i}"], "string", True))
                    i += 1
                return Lst(items)
            return None
        for name in names:
            value = env.get(name)
            if value is not None:
                return Scalar(value, "string", True)
        return None

    def _undefined(self, s: Subst) -> Result:
        """§7.2 step 4: nothing found anywhere."""
        if s.optional:
            return MISSING
        if s.list_suffix and self.use_env:
            base = ".".join(s.path)
            raise self._error(
                s,
                "could not resolve substitution",
                f"(no environment variables {base}_0, {base}_1, … set)",
            )
        if self.allow_unresolved:
            return Unresolved(s)
        raise self._error(s, "could not resolve substitution")

    def _error(self, s: Subst, what: str, detail: str = "") -> ResolveError:
        key = path_to_key(s.path) + ("[]" if s.list_suffix else "")
        origin = f"{self.opts.origin_description}: " if self.opts.origin_description else ""
        message = f"{origin}{what}: ${{{key}}}" + (f" {detail}" if detail else "")
        return ResolveError(message, key, s.line, s.col)


def _weight(v: Val) -> int:
    """A value's own weight for the post-cut value budget: 1, plus 1 per 16
    characters of scalar text or of its keys, plus its list items."""
    if isinstance(v, Scalar):
        return 1 + len(v.raw) // 16
    if isinstance(v, Lst):
        return 1 + len(v.items)
    if isinstance(v, Obj):
        return 1 + sum(len(k) for k in v.field_keys()) // 16
    return 1


def _source_nodes(root: Obj) -> int:
    """The number of values in the document."""
    n = 0
    todo: list[Val] = [root]
    while todo:
        v = todo.pop()
        n += 1
        if isinstance(v, Obj):
            for sl in v.fields.values():
                todo.extend(sl.stack)
        elif isinstance(v, Lst):
            todo.extend(v.items)
        elif isinstance(v, Concat):
            todo.extend(v.pieces)
    return n


def _shadowed(merged: Stack, e: Val) -> bool:
    """§3.2 W2: ``e`` is a non-empty object every key of which is already in
    the single object ``merged`` with a stack that ignores fallbacks."""
    if len(merged) != 1 or not isinstance(merged[0], Obj):
        return False
    if not isinstance(e, Obj):
        return False
    fields = e.fields  # e is a document entry: a plain object, never copied
    if not fields:
        return False
    top = merged[0]
    for k in fields:
        s = top.get_field(k)
        if s is None or not stack_ignores_fallbacks(s.stack):
            return False
    return True
