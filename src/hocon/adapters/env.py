"""Environment variables, and ``.env`` files, as HOCON config.

This is the bulk-mount case: a whole prefixed namespace becomes a config
subtree. Reading one variable needs nothing from here — HOCON's own ``${?VAR}``
already does that.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .._internal.os_text import is_undecodable
from ..config import Config
from ..value_factory import from_map
from . import AdapterError

__all__ = ["load", "parse_dotenv", "parse_dotenv_file"]

#: The double underscore that marks a path boundary, and the only thing that
#: does: a single underscore stays part of the segment, so ``APP_DB__MAX_CONN``
#: is ``db.max_conn``, and a literal ``.`` is key text, so ``APP_FOO.BAR`` is
#: the single key ``"foo.bar"`` rather than ``foo.bar`` (spec F1.2). Fixed
#: rather than configurable so the same variable name splits into the same
#: segments in every language's adapter (what those segments are then *called*
#: is the case-folding rule, :data:`_ASCII_FOLD`).
SEPARATOR = "__"

#: Segment characters that need no quoting when a path is spelled back out in
#: an error message. Deliberately conservative — anything else gets quotes.
_BARE_SEGMENT_CHARS = frozenset("abcdefghijklmnopqrstuvwxyz0123456789_-")

#: ASCII-only case fold (F1.3). Every other codepoint is left alone, so the
#: mapping is the same in all four implementations rather than inheriting each
#: standard library's Unicode case rules.
_ASCII_FOLD = str.maketrans("ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz")


def load(
    prefix: str,
    env: Mapping[str, str] | None = None,
    origin_description: str | None = None,
) -> Config:
    """Mount a prefixed slice of the environment.

    ``prefix`` is required: mounting everything would pull in PATH, HOME and
    whatever secrets happen to be set (spec F1.1).

    Two names reaching one path is an error rather than last-wins, the
    environment having no meaningful order to break the tie with (F1.6). The
    two names have to reach the *same segments*: ``APP_FOO.BAR`` and
    ``APP_FOO__BAR`` are different paths and coexist (F1.2).

    An entry under ``prefix`` whose name or value the OS could not decode as
    UTF-8 is an error too (F1.9b) — a mount that quietly dropped it would look
    complete while the operator's setting was missing. Entries outside the
    prefix are never inspected, so an undecodable variable elsewhere in the
    environment cannot break an unrelated mount.
    """
    if not prefix:
        raise AdapterError("env: a prefix is required when mounting the environment (spec F1.1)")
    source = os.environ if env is None else env

    # Sorted so a collision is reported the same way on every run.
    seen: dict[tuple[str, ...], str] = {}
    pairs: list[tuple[list[str], str]] = []
    for name in sorted(source):
        if not name.startswith(prefix):
            continue
        # F1.9b — deliberately after the prefix filter: a mount is an explicit
        # request for this namespace, so an entry in it the OS could not decode
        # is an error rather than a silent omission that leaves a stale default
        # winning invisibly. An undecodable variable *elsewhere* in the
        # environment stays none of this mount's business.
        if is_undecodable(name):
            raise AdapterError(
                f"env: the name {name!r} is not valid UTF-8 (spec F1.9); "
                f"a bulk mount of {prefix!r} cannot silently omit it"
            )
        if is_undecodable(source[name]):
            raise AdapterError(
                f"env: the value of {name!r} is not valid UTF-8 (spec F1.9); "
                f"a bulk mount of {prefix!r} cannot silently omit it"
            )
        path = _to_path(name[len(prefix) :], name)
        # The segments themselves are the identity — keyed as a tuple rather
        # than joined into a string, which would need a delimiter no segment
        # can contain and there is no such character (F1.2).
        key = tuple(path)
        if key in seen:
            # F1.6: two names can reach one path and the environment has no
            # meaningful order to break the tie with, so neither wins.
            # The names come from the environment, so they are rendered with !r
            # for the same reason the path is rendered by _render_path: a name
            # holding a newline or NUL would otherwise split or corrupt the
            # message a reader sees in a log.
            raise AdapterError(
                f"env: {seen[key]!r} and {name!r} both map to {_render_path(path)}"
            )
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
    return parse_dotenv(p.read_text(encoding="utf-8-sig"), prefix, str(p))


def _to_path(rest: str, name: str) -> list[str]:
    """Split the prefix-stripped name on ``__``, lowercasing each segment
    (F1.2, F1.3).

    The result stays a segment list end-to-end: joining on ``.`` and
    re-splitting later would turn a literal ``.`` in a variable name into a
    path boundary it never was, so ``APP_FOO.BAR`` is the single top-level key
    ``"foo.bar"``, distinct from ``APP_FOO__BAR`` (F1.2).

    Case folding is ASCII-only (F1.3). ``str.lower`` applies the full Unicode
    mapping, so ``İ`` (U+0130) would become ``i`` + U+0307 here while Go's
    simple mapping yields ``i`` — which would decide whether ``APP_İ`` collides
    with ``APP_I`` under F1.6 differently per language. Variable names are
    ASCII in every practical setting, so pinning the fold costs nothing.
    """
    segs = [s.translate(_ASCII_FOLD) for s in rest.split(SEPARATOR)]
    if any(s == "" for s in segs):
        raise AdapterError(f"env: {name!r} produces an empty path segment")
    return segs


def _render_path(segments: list[str]) -> str:
    """Spell a mapped path the way it would be written as a HOCON path
    expression: bare where a segment can be, quoted where it cannot.

    A collision message has to distinguish ``APP_FOO.BAR`` (one segment, so
    ``"foo.bar"``) from ``APP_FOO__BAR`` (two, so ``foo.bar``) — printing the
    dot-joined form for both would erase exactly the difference F1.2 draws.

    The quoted form is produced by :func:`json.dumps`, HOCON quoted strings
    being JSON string syntax. That escapes control characters too, so a name
    carrying a newline or a NUL cannot spray unprintables through the error
    message. ``ensure_ascii`` stays off so a non-ASCII segment is printed as
    itself — ASCII-only folding (F1.3) means such segments now reach here, and
    escaping them would drift from go.hocon's ``%q`` and rs.hocon's ``{:?}``.
    """
    out: list[str] = []
    for seg in segments:
        if seg and not set(seg) - _BARE_SEGMENT_CHARS:
            out.append(seg)
        else:
            out.append(json.dumps(seg, ensure_ascii=False))
    return ".".join(out)


def _nest(pairs: list[tuple[list[str], str]]) -> dict[str, Any]:
    """Nest pre-split segment paths, objects winning over scalars over the
    whole set so the outcome does not depend on input order (spec F1.8,
    mirroring F2.5).

    The sort is by path only and Python's is stable, so entries sharing a path
    keep their input order and the last one written wins — which is what a
    ``.env`` file's definite line order calls for (F0.7).
    """
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
