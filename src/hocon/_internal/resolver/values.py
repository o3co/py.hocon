"""Values of the resolution model (xx.hocon ``docs/resolution-model.md`` §1).

The structure builder turns the AST into these values, the resolver walks them,
and :mod:`.resolver` converts the result to the public :mod:`hocon.value` types.
Nothing outside this package sees them.

- :class:`Scalar`, :class:`Lst`, :class:`Obj`, :class:`Subst`, :class:`Concat`
  are the five value kinds of §1.1.
- :class:`Slot` is the pair (object, key) that holds a **stack**: every
  assignment of the key that was not dropped, top (latest) first. A stack is a
  plain ``list`` and never contains a stack.
- :class:`Partial` is a multi-entry merged value. It exists only while
  resolving under a restriction (§3.4).
- :class:`Unresolved` is what an undefined required substitution resolves to
  under ``allow_unresolved`` (§8.2). It is py's stand-in for Lightbend leaving
  the reference in place.
- :data:`MISSING` is "no value" (an undefined optional, an empty
  concatenation, a stack where nothing contributed).

Identity matters: a :class:`Subst` occurrence, a :class:`Concat` and a
:class:`Slot` are memoized and marked by instance (§5, §6), so none of them
defines ``__eq__``.
"""

from __future__ import annotations

from typing import Final

from ...value import ScalarValueType

__all__ = [
    "MISSING",
    "Concat",
    "Lst",
    "Missing",
    "Obj",
    "Partial",
    "Path",
    "Result",
    "Scalar",
    "Slot",
    "Stack",
    "Subst",
    "Unresolved",
    "Val",
    "Whitespace",
    "ignores_fallbacks",
    "is_resolved",
    "stack_ignores_fallbacks",
]

Path = tuple[str, ...]


class Scalar:
    """A string, number, boolean or null. ``raw`` is the source text (or the
    joined text of a concatenation). ``quoted`` records whether a string was
    written quoted: an unquoted string after a list or an object is dropped by
    a concatenation (§1.3 rule 3). Parser-inserted whitespace between pieces
    is an unquoted string."""

    __slots__ = ("quoted", "raw", "value_type")

    def __init__(self, raw: str, value_type: ScalarValueType, quoted: bool) -> None:
        self.raw = raw
        self.value_type = value_type
        self.quoted = quoted

    def is_unquoted_string(self) -> bool:
        return self.value_type == "string" and not self.quoted


class Whitespace(Scalar):
    """The whitespace the parser keeps between two concatenation pieces: an
    unquoted string."""

    __slots__ = ()

    def __init__(self, raw: str) -> None:
        super().__init__(raw, "string", False)


class Lst:
    """A list. Each item is one value; items are not stacks."""

    __slots__ = ("items",)

    def __init__(self, items: list[Val]) -> None:
        self.items = items


class Slot:
    """The pair (object, key) holding a stack (§1.1).

    ``path`` is the key's full path from the document root. ``synth`` is True
    for a slot created while resolving (§3.5): a view never maps it and a
    look-back never starts from it.
    """

    __slots__ = ("key", "path", "stack", "synth")

    def __init__(self, key: str, stack: Stack, path: Path, synth: bool = False) -> None:
        self.key = key
        self.stack = stack
        self.path = path
        self.synth = synth


class Obj:
    """An object: an insertion-ordered map from key to :class:`Slot`. ``flag``
    is ignoresFallbacks (§1.2), set only by the F6 rule of §2.1."""

    __slots__ = ("fields", "flag")

    def __init__(self, fields: dict[str, Slot] | None = None, flag: bool = False) -> None:
        self.fields: dict[str, Slot] = fields if fields is not None else {}
        self.flag = flag


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

    __slots__ = ("fpath", "line", "col", "pieces")

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


def is_resolved(v: Val) -> bool:
    """§1.2: no Subst and no stack with more than one entry anywhere inside."""
    if isinstance(v, Scalar):
        return True
    if isinstance(v, Lst):
        return all(is_resolved(i) for i in v.items)
    if isinstance(v, Obj):
        return all(len(s.stack) == 1 and is_resolved(s.stack[0]) for s in v.fields.values())
    return False


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
