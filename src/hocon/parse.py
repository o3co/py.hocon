"""Public parse entry points.

Mirrors ts.hocon ``src/parse.ts`` (``parse`` / ``parseFile`` / ``parseString``
and the ``*WithOptions`` variants). Python has no sync/async split at this
layer, so the ``parseAsync`` / ``parseFileAsync`` variants have no counterpart
here.
"""

from __future__ import annotations

from .config import Config

__all__ = ["parse", "parse_file", "parse_string"]


def parse(text: str) -> Config:
    """Parse HOCON source text and fully resolve it."""
    raise NotImplementedError("py.hocon is not implemented yet")


def parse_file(path: str) -> Config:
    """Parse a HOCON file (resolving relative includes against its directory)."""
    raise NotImplementedError("py.hocon is not implemented yet")


def parse_string(text: str) -> Config:
    """Parse HOCON source text without file context (includes are file-less)."""
    raise NotImplementedError("py.hocon is not implemented yet")
