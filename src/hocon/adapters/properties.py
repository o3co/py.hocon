"""``java.util.Properties`` files as HOCON config."""

from __future__ import annotations

from pathlib import Path

from .._internal.properties.properties import parse_properties
from ..config import Config
from ..value_factory import from_map

__all__ = ["parse", "parse_file"]


def parse(input_text: str, origin_description: str | None = None) -> Config:
    """Read Properties-syntax text.

    Shares its syntax layer with ``include "x.properties"``, so the two cannot
    drift apart. Values are all strings, and a ``${a.b}`` among them stays that
    literal text (spec F0.2, F2.2).
    """
    return from_map(parse_properties(input_text), origin_description)


def parse_file(path: str | Path) -> Config:
    """Read a Properties file, using its path as the origin description."""
    p = Path(path)
    return parse(p.read_text(encoding="utf-8-sig"), str(p))
