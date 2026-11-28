"""Values of the resolution model (xx.hocon ``docs/resolution-model.md`` §1).

The structure builder turns the AST into these values, the resolver walks them,
and :mod:`.resolver` converts the result to the public :mod:`hocon.value` types.
Nothing outside this package sees them.

- :class:`Scalar`, :class:`Lst`, :class:`Obj`, :class:`Subst`, :class:`Concat`
  are the five value kinds of §1.1.
- :class:`Slot` is the pair (object, key) that holds a **stack**: every
  assignment of the key that was not dropped, top (latest) first. A stack is a
  plain ``list`` and never contains a stack.
- An object is read through :meth:`Obj.get_field` / :meth:`Obj.field_keys` /
  :attr:`Obj.fields`. Objects built while resolving are lazy (§10.2): the
  merge overlay (:class:`.merge.Overlay`), the restricted :class:`Patch`, and
  the §5.5 :class:`.substituted.Substituted`. They compute a field only when
  it is asked for, and the full field map only when the object is iterated.
- :class:`Partial` is a multi-entry merged value. It exists only while
  resolving under a restriction (§3.4).
- :class:`Unresolved` is what stays unresolved under ``allow_unresolved``
  (§8.2). It is py's stand-in for Lightbend leaving the reference in place.
- :data:`MISSING` is "no value" (an undefined optional, an empty
  concatenation, a stack where nothing contributed).

Identity matters: a :class:`Subst` occurrence, a :class:`Concat` and a
:class:`Slot` are memoized and marked by instance (§5, §6), so none of them
defines ``__eq__``.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Final

from ...value import ScalarValueType

__all__ = [
    "MISSING",
    "Concat",
    "Lst",
    "Missing",
    "Obj",
    "Partial",
    "Patch",
    "Path",
    "Result",
    "Scalar",
    "Slot",
    "Stack",
    "Subst",
    "Unresolved",
    "Val",
    "carries_stack",
    "field_resolved",
    "freeze",
    "has_path",
    "ignores_fallbacks",
    "is_resolved",
    "stack_ignores_fallbacks",
]

Path = tuple[str, ...]


class Scalar:
    """A string, number, boolean or null. ``raw`` is the source text (or the
    joined text of a concatenation). ``quoted`` records whether a string was
    written quoted: only an unquoted whitespace string after a list or an
    object is dropped by a concatenation (§1.3 rule 3)."""

    __slots__ = ("quoted", "raw", "value_type")

    def __init__(self, raw: str, value_type: ScalarValueType, quoted: bool) -> None:
        self.raw = raw
        self.value_type = value_type
        self.quoted = quoted

    def is_unquoted_string(self) -> bool:
        return self.value_type == "string" and not self.quoted


class Lst:
    """A list. Each item is one value; items are not stacks."""

    __slots__ = ("items",)

    def __init__(self, items: list[Val]) -> None:
        self.items = items


class Slot:
    """The pair (object, key) holding a stack (§1.1).

    ``path`` is the key's full path from the document root. ``synth`` is True
    for a slot created while resolving (§3.5, a merged leaf): a view maps it by
    its path and its entries (:meth:`content`), not by identity. ``origin`` is
    the slot this slot stands for: itself, or the slot whose
    view-mapped stack it carries through a restricted lookup (§3.4), or that
    a §5.5 rewrite derives from. A derived slot keeps ``synth``: an alias of a
    merged leaf is that merged leaf, never a document slot (§10.1). A view
    maps a document slot through its origin.
    """

    __slots__ = ("_content", "key", "origin", "path", "stack", "synth")

    def __init__(
        self,
        key: str,
        stack: Stack,
        path: Path,
        synth: bool = False,
        origin: Slot | None = None,
    ) -> None:
        self.key = key
        self.stack = stack
        self.path = path
        self.synth = synth
        self.origin: Slot = origin if origin is not None else self
        self._content: tuple[int, ...] | None = None

    def content(self) -> tuple[int, ...]:
        """A merged leaf's identity besides its path (§3.5): the entry
        instances it is built from. A slot derived from another (an alias of
        §3.4, a §5.5 rewrite) answers with its origin's, so it has the same
        identity. Only asked for while resolving, when stacks no longer
        change."""
        if self.origin is not self:
            return self.origin.content()
        if self._content is None:
            self._content = tuple(id(x) for x in self.stack)
        return self._content


class Obj:
    """An object: an insertion-ordered map from key to :class:`Slot`. ``flag``
    is ignoresFallbacks (§1.2), set only by the F6 rule of §2.1.

    ``frozen`` objects never change again, so "resolved" and "carries ignored
    fallbacks" are computed once (§10.2). The structure builder makes its
    objects unfrozen and freezes the tree when it is done (:func:`freeze`);
    everything made while resolving is frozen from the start.
    """

    __slots__ = ("_car", "_fields", "_flag", "_res", "_unres", "frozen")

    def __init__(
        self, fields: dict[str, Slot] | None = None, flag: bool = False, frozen: bool = True
    ) -> None:
        self._fields: dict[str, Slot] | None = fields if fields is not None else {}
        self._flag = flag
        self.frozen = frozen
        self._res: bool | None = None
        self._car: bool | None = None
        self._unres: list[str] | None = None

    @property
    def flag(self) -> bool:
        return self._flag

    @property
    def fields(self) -> dict[str, Slot]:
        """The full field map. A lazy object builds it on first use."""
        assert self._fields is not None
        return self._fields

    def get_field(self, k: str) -> Slot | None:
        return self.fields.get(k)

    def field_keys(self) -> list[str]:
        return list(self.fields)

    def is_resolved(self) -> bool:
        """§1.2: every field holds one resolved entry."""
        if self._res is None or not self.frozen:
            self._res = _resolved_tree(self)
        return self._res

    def unresolved_keys(self) -> Iterator[str]:
        """The keys whose field is not a single resolved value (§10.2 item 5).
        A plain object lists them once; an object built while resolving
        yields them lazily, without building its field map."""
        if self._unres is None or not self.frozen:
            self._unres = [k for k, s in self.fields.items() if not field_resolved(s)]
        return iter(self._unres)

    def carries(self) -> bool:
        """§5.5: flagged, or a child stack carries ignored fallbacks."""
        if self._car is None or not self.frozen:
            self._car = self.flag or any(carries_stack(s.stack) for s in self.fields.values())
        return self._car


class Patch(Obj):
    """§3.4 restricted object: ``base`` with one key replaced (``field``) or
    removed (``field`` is None), without copying the other keys (§10.2)."""

    __slots__ = ("base", "field", "key")

    def __init__(self, base: Obj, key: str, field: Slot | None) -> None:
        super().__init__(None, base.flag)
        self._fields = None  # built on first iteration
        self.base = base
        self.key = key
        self.field = field

    @property
    def fields(self) -> dict[str, Slot]:
        if self._fields is None:
            out = dict(self.base.fields)
            if self.field is None:
                out.pop(self.key, None)
            else:
                out[self.key] = self.field
            self._fields = out
        return self._fields

    def get_field(self, k: str) -> Slot | None:
        return self.field if k == self.key else self.base.get_field(k)

    def unresolved_keys(self) -> Iterator[str]:
        # §10.2 item 5: only the replaced key can differ from the base, so no
        # field map is built.
        for k in self.base.unresolved_keys():
            if k != self.key:
                yield k
        if self.field is not None and not field_resolved(self.field):
            yield self.key

    def is_resolved(self) -> bool:
        if self._res is None:
            self._res = next(self.unresolved_keys(), None) is None
        return self._res

    def field_keys(self) -> list[str]:
        return list(self.fields)


class Subst:
    """One ``${…}`` / ``${?…}`` occurrence.

    ``path`` is the full path, relativized by an include (§7.1);
    ``prefix_len`` is the number of segments the include added, so
    ``path[prefix_len:]`` is the path as written. ``list_suffix`` marks
    ``${X[]}`` (S13c). ``line`` / ``col`` locate it for error messages.
    """

    __slots__ = ("col", "line", "list_suffix", "optional", "path", "prefix_len")

    def __init__(
        self,
        path: Path,
        optional: bool,
        prefix_len: int = 0,
        list_suffix: bool = False,
        line: int = 0,
        col: int = 0,
    ) -> None:
        self.path = path
        self.optional = optional
        self.prefix_len = prefix_len
        self.list_suffix = list_suffix
        self.line = line
        self.col = col


class Concat:
    """A value concatenation that still has a :class:`Subst` among its pieces
    after parse-time consolidation (§1.4). ``fpath`` is the path of the field
    the concatenation is written in; the concatenation memo keys on the view's
    mappings strictly below it (§5.2)."""

    __slots__ = ("col", "fpath", "line", "pieces")

    def __init__(self, pieces: list[Val], fpath: Path, line: int = 0, col: int = 0) -> None:
        self.pieces = pieces
        self.fpath = fpath
        self.line = line
        self.col = col


class Partial:
    """A merged value with several entries, top first (§3.2, §3.4). Produced
    only by a stack walk under a restriction."""

    __slots__ = ("stack",)

    def __init__(self, stack: Stack) -> None:
        self.stack = stack


class Unresolved:
    """What stays unresolved under ``allow_unresolved`` (§8.2): an undefined
    required substitution, or a concatenation holding one. It absorbs the
    field, list item or concatenation it appears in. ``value`` is the model
    value that could not be resolved."""

    __slots__ = ("value",)

    def __init__(self, value: Subst | Concat) -> None:
        self.value = value


class Missing:
    """The type of :data:`MISSING`."""

    __slots__ = ()

    def __repr__(self) -> str:
        return "MISSING"


MISSING: Final = Missing()

Val = Scalar | Lst | Obj | Subst | Concat | Partial | Unresolved
Stack = list[Val]
# What resolving a value can give: a value or MISSING.
Result = Val | Missing


def field_resolved(s: Slot) -> bool:
    """A field holds a single resolved value."""
    return len(s.stack) == 1 and is_resolved(s.stack[0])


def is_resolved(v: Val) -> bool:
    """§1.2: no Subst and no stack with more than one entry anywhere inside."""
    if isinstance(v, Scalar):
        return True
    if isinstance(v, Lst):
        return all(is_resolved(i) for i in v.items)
    if isinstance(v, Obj):
        return v.is_resolved()
    return False


def _resolved_tree(root: Obj) -> bool:
    """``root`` is resolved: walked without recursion through plain objects
    and lists, so a deeply nested document does not hit the interpreter's
    recursion limit. A lazy object (overlay, patch, substituted) answers for
    itself. When the answer is yes, every frozen plain object on the way is
    resolved too and remembers it."""
    seen: list[Obj] = []
    todo: list[Val] = []
    for s in root.fields.values():
        if len(s.stack) != 1:
            return False
        todo.append(s.stack[0])
    while todo:
        v = todo.pop()
        if isinstance(v, Scalar):
            continue
        if isinstance(v, Lst):
            todo.extend(v.items)
            continue
        if type(v) is Obj:
            if v.frozen and v._res is not None:
                if not v._res:
                    return False
                continue
            seen.append(v)
            for s in v.fields.values():
                if len(s.stack) != 1:
                    return False
                todo.append(s.stack[0])
            continue
        if isinstance(v, Obj):
            if not v.is_resolved():
                return False
            continue
        return False  # a substitution, a concatenation, a partial stack
    for o in seen:
        if o.frozen:
            o._res = True
    return True


def ignores_fallbacks(v: Val) -> bool:
    """§1.2: a scalar always; a list when it is resolved; an object by its flag;
    a substitution, a concatenation (and anything else) never."""
    if isinstance(v, Scalar):
        return True
    if isinstance(v, Lst):
        return is_resolved(v)
    if isinstance(v, Obj):
        return v.flag
    return False


def stack_ignores_fallbacks(st: Stack) -> bool:
    """§1.2: a stack ignores fallbacks exactly when its *last* entry does."""
    return ignores_fallbacks(st[-1])


def carries_stack(st: Stack) -> bool:
    """§5.5 "carries ignored fallbacks" for a stack: one entry carries it, or a
    multi-entry stack ignores fallbacks or has an entry that carries it.
    Scalars, lists, substitutions and concatenations never carry it."""
    if len(st) == 1:
        e = st[0]
        return isinstance(e, Obj) and e.carries()
    return stack_ignores_fallbacks(st) or any(isinstance(e, Obj) and e.carries() for e in st)


def has_path(v: Val, path: Path) -> bool:
    """§5.3 presence: whether a resolved value has the whole ``path``."""
    for k in path:
        s = v.get_field(k) if isinstance(v, Obj) else None
        if s is None or len(s.stack) != 1:
            return False
        v = s.stack[0]
    return True


def freeze(v: Val) -> None:
    """Mark every object of a finished tree frozen (§10.2). A frozen object's
    subtree is frozen already, so the walk stops there."""
    todo: list[Val] = [v]
    while todo:
        x = todo.pop()
        if isinstance(x, Obj):
            if x.frozen:
                continue
            x.frozen = True
            x._res = x._car = None  # anything computed while it could still change
            x._unres = None
            for s in x.fields.values():
                todo.extend(s.stack)
        elif isinstance(x, Lst):
            todo.extend(x.items)
        elif isinstance(x, Concat):
            todo.extend(x.pieces)
