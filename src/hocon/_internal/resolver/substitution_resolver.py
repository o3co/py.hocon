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
from .merge import consolidate, fallback, fold_entries
from .types import ResolveOptions
from .utils import path_to_key
from .values import (
    MISSING,
    Concat,
    Lst,
    Missing,
    Obj,
    Partial,
    Path,
    Result,
    Scalar,
    Slot,
    Stack,
    Subst,
    Unresolved,
    Val,
    is_resolved,
    stack_ignores_fallbacks,
)
from .views import ROOT_VIEW, Empty, Substitute, Substitutes, View, ViewKey

__all__ = ["SubstitutionResolver"]


class _ReEntry(Exception):
    """§6.2: a re-entry, caught by the innermost active substitution frame
    (§6.3). ``kind`` is ``"marker"`` for an active ``(Subst, View)`` needed
    again (case a) and ``"empty"`` for a lookup that reached EMPTY (case b)."""

    def __init__(self, kind: Literal["marker", "empty"]) -> None:
        super().__init__(kind)
        self.kind = kind


def _fold_resolved(entries: Stack) -> Stack:
    return fold_entries(entries, synth=True)


class SubstitutionResolver:
    def __init__(self, root: Obj, opts: ResolveOptions) -> None:
        self.root = root
        self.opts = opts
        self.memo = Memo()
        self.substitutes = Substitutes(_fold_resolved)
        # §6.1: the active (Subst, View) pairs.
        self.active: set[tuple[int, ViewKey]] = set()
        self.use_env = opts.use_system_environment is not False
        self.allow_unresolved = bool(opts.allow_unresolved)

    def resolve(self) -> Val:
        """§3.1: the root object, resolved in the root view."""
        return self._resolve_obj(self.root, ROOT_VIEW, None)

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
            # a key the full result lacks is decided by the restricted walk.
            if isinstance(full, Obj) and restrict[0] in full.fields:
                return full
        key = (slot, id(st), below, restrict)
        if restrict is not None:
            hit = self.memo.stack(key)
            if hit is not None:
                return hit
        # The walk (W1–W5): the entries top first, each folded under the
        # result so far, until the result ignores fallbacks.
        merged: Stack | None = None
        r: Result
        for i, e in enumerate(st):
            if merged is not None and stack_ignores_fallbacks(merged):  # W1 cut
                break
            if isinstance(e, (Subst, Concat)):
                # W3 look-back: below this entry, the slot shows the rest of its
                # stack. A single entry or a synthesized slot makes no view.
                inner = view
                if len(st) > 1 and not slot.synth:
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
            merged = rs if merged is None else fallback(merged, rs, synth=True)
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
        # §3.4: only key k changes. An EMPTY slot stays, so that find reaches it.
        k, rest = restrict[0], restrict[1:]
        child = o.fields.get(k)
        if child is None or not rest or isinstance(self._stack_of(child, view), Empty):
            return o
        r = self._value_of(child, view, rest)
        fields = dict(o.fields)
        if isinstance(r, Missing):
            del fields[k]
        elif isinstance(r, Partial):
            fields[k] = Slot(k, r.stack, child.path, True)
        else:
            fields[k] = Slot(k, [r], child.path, True)
        return Obj(fields, o.flag)

    def _resolve_concat(self, c: Concat, view: View) -> Result:
        """§1.3 with the concatenation memo of §5.2. Pieces resolve
        unrestricted, even under a restriction (§3.4)."""
        key = (id(c), view.below(c.fpath, strict=True))
        hit = self.memo.concat(key)
        if hit is not None:
            return hit
        resolved: list[Val] = []
        for p in c.pieces:
            if isinstance(p, Subst):
                r = self._resolve_subst(p, view, None)
            else:
                r = self._resolve(p, view, None)
            if isinstance(r, Missing):  # §1.3: an omitted optional piece
                continue
            if isinstance(r, Unresolved):
                return r
            resolved.append(r)
        if self.allow_unresolved and not all(is_resolved(r) for r in resolved):
            # An object or a list piece that holds an unresolved value cannot
            # be joined; the concatenation stays unresolved as a whole.
            return Unresolved(c)
        result: Result = MISSING  # every piece omitted
        if resolved:
            joined = consolidate(resolved, at_parse=False, line=c.line, col=c.col)
            if len(joined) != 1:
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
            return v.fields.get(key)
        if isinstance(v, Partial):
            parts: list[Stack] = []
            for layer in v.stack:
                if not isinstance(layer, Obj):
                    break
                s = layer.fields.get(key)
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
        first = self.root.fields.get(path[0])
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
            if not (restrict and isinstance(result, Obj) and restrict[0] not in result.fields):
                return result
            # §5.3 presence: decided by a restricted resolution in the view
            # that produced the memoized result.
            view = computed_in
        marker = (id(s), view.key)
        if marker in self.active:
            raise _ReEntry("marker")  # §6.2 (a)
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
                if isinstance(r, Missing) and not s.optional:
                    if not self.allow_unresolved:
                        raise self._error(s, "could not resolve substitution")
                    r = Unresolved(s)
        except _ReEntry as e:
            # §6.3 [interim]: the innermost active frame catches. Work done
            # since the frame's mark is abandoned (§5.4).
            self.memo.rollback(mark)
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


def _shadowed(merged: Stack, e: Val) -> bool:
    """§3.2 W2: ``e`` is a non-empty object every key of which is already in
    the single object ``merged`` with a stack that ignores fallbacks."""
    if len(merged) != 1 or not isinstance(merged[0], Obj):
        return False
    if not isinstance(e, Obj) or not e.fields:
        return False
    top = merged[0].fields
    for k in e.fields:
        s = top.get(k)
        if s is None or not stack_ignores_fallbacks(s.stack):
            return False
    return True
