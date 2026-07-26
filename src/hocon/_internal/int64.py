"""The int64 range HOCON integers occupy (spec F0.5).

Python's ``int`` is unbounded, so the bound has to be stated rather than
inherited from the type. It lives here because two callers share it — the
public ``from_map`` factory and the adapters' leaf rule — and because it is an
implementation detail of that rule rather than API: ts.hocon keeps its
``INT64_MAX`` / ``INT64_MIN`` module-private for the same reason.
"""

from __future__ import annotations

__all__ = ["INT64_MAX", "INT64_MIN"]

INT64_MIN = -(2**63)
INT64_MAX = 2**63 - 1
