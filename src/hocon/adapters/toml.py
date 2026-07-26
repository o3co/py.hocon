"""TOML documents as HOCON config, via the standard library's :mod:`tomllib`.

No extra dependency: Python 3.11 ships a TOML parser, and this package already
requires 3.11.

TOML's types line up with HOCON's apart from dates: HOCON has no datetime, so
all four TOML date-time types become their ISO 8601 string forms, which is the
honest representation rather than a lossy number (spec F4.2).
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

from .._internal.text import strip_bom
from ..config import Config
from ..value_factory import from_map
from . import AdapterError
from ._tree import common_scalar, object_root

__all__ = ["parse", "parse_file"]


def parse(input_text: str, origin_description: str | None = None) -> Config:
    """Read TOML text."""
    try:
        doc = tomllib.loads(strip_bom(input_text))
    except tomllib.TOMLDecodeError as e:
        raise AdapterError(f"toml: {e}") from None
    return from_map(object_root(doc, "toml", _scalar), origin_description)


def parse_file(path: str | Path) -> Config:
    """Read a TOML file, using its path as the origin description."""
    p = Path(path)
    return parse(p.read_text(encoding="utf-8-sig"), str(p))


def _scalar(v: Any, at: str) -> Any:
    return common_scalar(v, at, "toml")
