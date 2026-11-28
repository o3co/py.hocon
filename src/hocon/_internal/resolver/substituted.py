"""§5.5: a substituted object does not carry ignored fallbacks
(xx.hocon ``docs/resolution-model.md``; Lightbend 1.4.10
ConfigReference.java:113-122, SimpleConfigObject.java:75-91, 244-284).

The ignoresFallbacks flag is a merge instruction for the key whose history
held a non-object. It is not part of the value a substitution copies, so when
a ``${}`` resolves to an object, the result is :class:`Substituted`: the same
object with every flag cleared, and, in an object that is not resolved yet
(a partial result under a restriction), every child that carries ignored
fallbacks replaced by a new reference to the same path. Fields are rewritten
only when asked for, so a lookup through the result touches only its path
(§10.2).
"""

from __future__ import annotations

from .values import Obj, Path, Slot, Subst, carries_stack

__all__ = ["Substituted"]


class Substituted(Obj):
    """``base`` as the substitution ``subst`` returns it, at ``path``.

    A value that is already a :class:`Substituted` carries no flag and no
    child that carries one, so rewriting it again would change nothing but
    object identity; it is used as it is (this keeps a chain of substituted
    objects from nesting one wrapper per level). This departs from the
    reference model, which wraps again. No result can observe it: the second
    wrap would create no reference (nothing carries), its path is used only
    for references, and a merged leaf built through two different
    substitutions differs in another entry anyway (§3.5 identity). Checked on
    34,000 generated documents against a copy that wraps again."""

    __slots__ = ("_cache", "base", "path", "subst")

    def __init__(self, base: Obj, subst: Subst, path: Path) -> None:
        super().__init__(None, False)
        self._fields = None  # built on first iteration
        self.base = base
        self.subst = subst
        self.path = path
        # §5.5 distinguishes a resolved base (flags cleared) from an
        # unresolved one (carrying children deferred). The rule below applies
        # the second form to both: for a resolved base it gives the same
        # children (every child object is resolved, so it is rewritten, and no
        # other child carries anything), without asking whether the whole
        # base is resolved, which would materialize it (§10.2).
        self._cache: dict[str, Slot | None] = {}

    def get_field(self, k: str) -> Slot | None:
        if self._fields is not None:
            return self._fields.get(k)
        if k in self._cache:
            return self._cache[k]
        f = self.base.get_field(k)
        if f is not None:
            top = f.stack[0]
            if len(f.stack) == 1 and isinstance(top, Obj):
                # A child object goes through the same rule (flags cleared, or
                # deferred below it), unless it is unresolved and clean.
                if isinstance(top, Substituted):
                    pass  # already rewritten: nothing left to clear or defer
                elif top.is_resolved() or carries_stack(f.stack):
                    inner = Substituted(top, self.subst, (*self.path, k))
                    f = Slot(k, [inner], f.path, f.synth, f.origin)
            elif carries_stack(f.stack):
                # Any other child that carries ignored fallbacks is replaced by
                # a reference to the same path, resolved later like any other.
                s = self.subst
                ref = Subst((*self.path, k), s.optional, s.prefix_len, False, s.line, s.col)
                f = Slot(k, [ref], f.path, True)
        self._cache[k] = f
        return f

    def field_keys(self) -> list[str]:
        return list(self.fields)

    @property
    def fields(self) -> dict[str, Slot]:
        if self._fields is None:
            fields: dict[str, Slot] = {}
            for k in self.base.field_keys():
                s = self.get_field(k)
                assert s is not None
                fields[k] = s
            self._fields = fields
        return self._fields

    def is_resolved(self) -> bool:
        if self._res is None:
            self._res = self.base.is_resolved()
        return self._res

    def carries(self) -> bool:
        return False
