"""Bounds on how deep a config tree may go, and the words for saying so.

Two different limits live here because two different things can be too deep.

``MAX_PATH_SEGMENTS`` bounds a *name* that maps to a path — an environment
variable's ``__`` segments, a Properties file's dotted key. One name produces
one arbitrarily deep chain, so the input needed to exhaust the stack is tiny:
1.5 kB of variable name reached 497 levels. rs.hocon capped the same mapping at
64 for the same reason (its version aborted the process rather than raising),
and this repeats that number so a name that mounts in one implementation mounts
in the other.

Deeply nested *documents* get no such cap: refusing a 65-level JSON document
would be a claim about the format, not about a name we invented a mapping for.
They get :func:`guard_recursion` instead, which turns the interpreter's
``RecursionError`` into whichever error the caller's contract names. That
matters beyond tidiness: the depth at which CPython gives out depends on how
deep the *caller* already is, so the same document can load from one call site
and fail from another. Neither outcome should be an exception type the
documented ``except`` clause misses.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar

__all__ = ["MAX_PATH_SEGMENTS", "guard_recursion", "too_deep"]

#: Ceiling on the number of path segments one name may map to (F1.2 for env,
#: S23.x for Properties). Matches rs.hocon's ``MAX_DEPTH``.
MAX_PATH_SEGMENTS = 64

T = TypeVar("T")


def too_deep(segments: int) -> bool:
    """Report whether a mapped path is over :data:`MAX_PATH_SEGMENTS`."""
    return segments > MAX_PATH_SEGMENTS


def guard_recursion(fn: Callable[[], T], wrap: Callable[[str], Exception]) -> T:
    """Run ``fn``, turning a ``RecursionError`` into ``wrap(message)``.

    ``RecursionError`` is outside every error type this library documents, so a
    caller writing ``except ConfigError`` or ``except AdapterError`` does not
    catch it and the failure escapes as an interpreter-level error from
    somewhere in the middle of a parse.

    The message names the possibilities rather than asserting one, because from
    inside the handler they are indistinguishable: input nested past what the
    interpreter's stack holds, a *cyclic* input structure (a dict that contains
    itself, handed to ``from_map``), or — least likely — a cycle in this
    library. Naming only depth would send a reader looking for nesting that is
    not there when the real shape is a cycle.
    """
    try:
        return fn()
    except RecursionError:
        raise wrap(
            "input is nested too deeply for this interpreter's stack, or "
            "contains a cycle (raise sys.setrecursionlimit, flatten the "
            "document, or break the cycle)"
        ) from None
