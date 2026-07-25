"""Environment variables, and ``.env`` files, as HOCON config.

This is the bulk-mount case: a whole prefixed namespace becomes a config
subtree. Reading one variable needs nothing from here — HOCON's own ``${?VAR}``
already does that.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from ..config import Config
from ..value_factory import from_map
from . import AdapterError

__all__ = ["load", "parse_dotenv", "parse_dotenv_file"]

#: The double underscore that marks a path boundary; a single one stays part of
#: the segment, so ``APP_DB__MAX_CONN`` is ``db.max_conn`` (spec F1.2). Fixed
#: rather than configurable so every language's adapter nests identically.
SEPARATOR = "__"


def load(
    prefix: str,
    env: Mapping[str, str] | None = None,
    origin_description: str | None = None,
) -> Config:
    """Mount a prefixed slice of the environment.

    ``prefix`` is required: mounting everything would pull in PATH, HOME and
    whatever secrets happen to be set (spec F1.1).
    """
    if not prefix:
        raise AdapterError("env: a prefix is required when mounting the environment (spec F1.1)")
    source = os.environ if env is None else env

    # Sorted so a collision is reported the same way on every run.
    seen: dict[str, str] = {}
    pairs: list[tuple[list[str], str]] = []
    for name in sorted(source):
        if not name.startswith(prefix):
            continue
        path = _to_path(name[len(prefix) :], name)
        # NUL cannot appear in a segment, so distinct paths cannot collide
        # into one detection key the way a "." join would let them (F1.2).
        key = "\x00".join(path)
        if key in seen:
            # F1.6: two names can reach one path and the environment has no
            # meaningful order to break the tie with, so neither wins.
            raise AdapterError(f"env: {seen[key]} and {name} both map to {'.'.join(path)!r}")
        seen[key] = name
        pairs.append((path, source[name]))

    return from_map(_nest(pairs), origin_description or "environment variables")


def parse_dotenv(
    input_text: str,
    prefix: str = "",
    origin_description: str | None = None,
) -> Config:
    """Read ``.env`` file content.

    The dialect is deliberately small (spec F1.7): ``NAME=value``, an optional
    ``export`` prefix, whole-line ``#`` comments, single quotes taken literally,
    double quotes with ``\\n \\r \\t \\\\ \\"``. Multi-line values and trailing
    comments are unsupported — an unquoted value containing ``" #"`` is an error
    rather than a guess. No ``${...}`` expansion.
    """
    origin = origin_description or ".env"
    pairs: list[tuple[list[str], str]] = []

    normalized = input_text.replace("\r\n", "\n").replace("\r", "\n")
    for lineno, raw in enumerate(normalized.split("\n"), start=1):
        line = raw.strip()
        if line == "" or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :]
        name, sep, rest = line.partition("=")
        if not sep:
            raise AdapterError(f"{origin}:{lineno}: expected NAME=value")
        name = name.strip()
        if name == "":
            raise AdapterError(f"{origin}:{lineno}: empty variable name")
        value = _dotenv_value(rest.lstrip(" \t"), origin, lineno, name)
        if not name.startswith(prefix):
            continue
        pairs.append((_to_path(name[len(prefix) :], name), value))

    # A file has a definite line order, so a repeated name is last-wins (F0.7)
    # rather than the collision error the environment gets.
    return from_map(_nest(pairs), origin)


def parse_dotenv_file(path: str | Path, prefix: str = "") -> Config:
    """Read a ``.env`` file, using its path as the origin description."""
    p = Path(path)
    return parse_dotenv(p.read_text(encoding="utf-8"), prefix, str(p))


def _to_path(rest: str, name: str) -> list[str]:
    """Split the prefix-stripped name on ``__``, lowercasing each segment
    (F1.2, F1.3).

    The result stays a segment list end-to-end: joining on ``.`` and
    re-splitting later would turn a literal ``.`` in a variable name into a
    path boundary it never was, so ``APP_FOO.BAR`` is the single top-level key
    ``"foo.bar"``, distinct from ``APP_FOO__BAR`` (F1.2).
    """
    segs = [s.lower() for s in rest.split(SEPARATOR)]
    if any(s == "" for s in segs):
        raise AdapterError(f"env: {name!r} produces an empty path segment")
    return segs


def _nest(pairs: list[tuple[list[str], str]]) -> dict[str, Any]:
    """Nest pre-split segment paths, objects winning over scalars over the
    whole set so the outcome does not depend on input order (spec F1.8,
    mirroring F2.5)."""
    root: dict[str, Any] = {}
    for segments, value in sorted(pairs, key=lambda kv: kv[0]):
        current = root
        for seg in segments[:-1]:
            existing = current.get(seg)
            if not isinstance(existing, dict):
                current[seg] = {}
            current = current[seg]
        last = segments[-1]
        if not isinstance(current.get(last), dict):
            current[last] = value
    return root


def _dotenv_value(v: str, origin: str, lineno: int, name: str) -> str:
    def fail(msg: str) -> AdapterError:
        return AdapterError(f"{origin}:{lineno}: {name}: {msg}")

    if v.startswith("'"):
        end = v.find("'", 1)
        if end == -1:
            raise fail("unterminated ' quote (multi-line values are not supported)")
        if v[end + 1 :].strip() != "":
            raise fail("unexpected text after the closing quote")
        return v[1:end]

    if v.startswith('"'):
        out: list[str] = []
        i = 1
        while i < len(v):
            c = v[i]
            if c == '"':
                if v[i + 1 :].strip() != "":
                    raise fail("unexpected text after the closing quote")
                return "".join(out)
            if c == "\\":
                i += 1
                if i >= len(v):
                    raise fail("dangling \\ at end of line")
                esc = v[i]
                mapped = {"n": "\n", "r": "\r", "t": "\t", "\\": "\\", '"': '"'}.get(esc)
                if mapped is None:
                    raise fail(f'unknown escape \\{esc} (supported: \\n \\r \\t \\\\ \\")')
                out.append(mapped)
            else:
                out.append(c)
            i += 1
        raise fail('unterminated " quote (multi-line values are not supported)')

    trimmed = v.rstrip(" \t")
    for i in range(1, len(trimmed)):
        if trimmed[i] == "#" and trimmed[i - 1] in " \t":
            raise fail(
                f"ambiguous value {trimmed!r}: trailing comments are not supported, "
                "so quote the value if the # belongs to it"
            )
    return trimmed
