"""Read config formats owned by *other* programs as HOCON.

Each adapter returns a fully resolved :class:`~hocon.Config` you place under
your own document with :meth:`~hocon.Config.with_fallback`, so a ``${...}`` can
reach into it::

    from hocon.adapters import env

    base = env.load(prefix="APP_")            # APP_DB__HOST -> db.host
    cfg = hocon.parse(src, resolve_substitutions=False)
    merged = cfg.with_fallback(base).resolve()

Deferring resolution matters: the plain parse resolves as it goes, so a
``${...}`` aimed at the fallback would fail before the fallback is attached.

``properties``, ``env``, ``jsonc`` and ``toml`` need nothing beyond the standard
library — TOML is read with :mod:`tomllib`, which Python 3.11 ships. ``yaml``
needs an extra: ``pip install hocon-parser[yaml]``.

Foreign data stays data: a ``${a.b}`` in an ingested value is literal text,
never a reference (spec F0.2). Ingestion is AST-level — a document is decoded
and turned into a value tree, never rendered to HOCON text.

See the format-ingestion mapping spec:
https://github.com/o3co/xx.hocon/blob/main/docs/format-ingestion-mapping.md
"""

from __future__ import annotations

__all__ = ["AdapterError"]


class AdapterError(Exception):
    """Raised when a foreign document cannot be mapped onto HOCON.

    The message cites the spec item where one applies.
    """
