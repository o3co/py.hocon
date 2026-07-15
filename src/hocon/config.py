"""``Config`` — the resolved-configuration handle returned by the parse entry
points.

Mirrors ts.hocon ``src/config.ts``. Accessor naming follows rs.hocon's
snake_case surface (``get_string`` / ``get_int`` / ``get_duration`` /
``get_period`` …), which is already idiomatic Python. Period accessors
(S20.1–S20.4) are in scope: port their behavior from rs.hocon, the only
sibling that implements them.
"""

from __future__ import annotations

__all__ = ["Config"]


class Config:
    """Resolved (or partially resolved) HOCON configuration.

    TODO(port): mirror the ts.hocon Config surface (getters, ``resolve()``,
    ``with_fallback()``, unresolved-state semantics per E12) with snake_case
    accessor names per rs.hocon.
    """

    def __init__(self) -> None:
        raise NotImplementedError("py.hocon is not implemented yet")
