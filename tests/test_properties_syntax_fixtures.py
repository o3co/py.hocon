"""S23.5 / S23.6 Java-properties syntax fixtures (properties-syntax/ps01–ps05).

Companion to ``test_properties_conflict_fixtures.py``, driven the same way: wrap
each ``.properties`` file in a one-line ``include file("<abs path>")`` document
and compare the resolved tree against the ``-expected.json`` sidecar generated
from Lightbend, which reads the file with ``java.util.Properties``.

Pins:

- **S23.5** (HOCON.md L1587) — backslash continuations join, an even run of
  trailing backslashes does not continue, and a continuation line starting with
  ``#`` is value text. Also the separator rules that come with it: ``=``, ``:``
  or whitespace, and a value keeping its trailing whitespace.
- **S23.6** (L1587) — the ``\\t \\n \\r \\f`` and ``\\uXXXX`` escapes, an unknown
  escape dropping its backslash, an escaped separator belonging to the key, and
  a surrogate pair forming its astral character.

Both were out-of-scope until 2026-07-24.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

import hocon

_TESTDATA = Path(__file__).parent / "conformance" / "testdata"
_EXPECTED = _TESTDATA / "expected" / "properties-syntax"
_PROPS = _TESTDATA / "hocon" / "properties-syntax"

_KNOWN_STEMS = {
    "ps01-continuation",
    "ps02-escapes",
    "ps03-separators",
    "ps04-value-whitespace",
    "ps05-astral",
}

pytestmark = pytest.mark.skipif(
    not _EXPECTED.is_dir() or not _PROPS.is_dir(),
    reason="properties-syntax corpus not synced — run `make testdata`",
)


def _norm(v: Any) -> Any:
    """Canonicalize a JSON value for comparison (same shape as the corpus
    runner's normalization: key order ignored, numbers by value, null keys
    dropped)."""
    if isinstance(v, dict):
        return {k: _norm(x) for k, x in v.items() if x is not None}
    if isinstance(v, list):
        return [_norm(x) for x in v]
    if isinstance(v, bool):
        return ("bool", v)
    if isinstance(v, (int, float)):
        return ("num", float(v))
    if v is None:
        return ("null",)
    return ("str", v)


def _discover() -> list[tuple[str, Path, Any]]:
    fixtures: list[tuple[str, Path, Any]] = []
    if not _EXPECTED.is_dir():
        return fixtures
    for exp_path in sorted(_EXPECTED.glob("*-expected.json")):
        stem = exp_path.name[: -len("-expected.json")]
        props = _PROPS / f"{stem}.properties"
        if not props.is_file():
            continue
        expected = json.loads(exp_path.read_text(encoding="utf-8"))
        fixtures.append((stem, props, expected))
    return fixtures


_FIXTURES = _discover()


@pytest.mark.parametrize(
    "stem,props,expected", _FIXTURES, ids=[stem for stem, _, _ in _FIXTURES]
)
def test_properties_syntax_fixture(stem: str, props: Path, expected: Any) -> None:
    wrapper = f'include file("{props.resolve().as_posix()}")'
    cfg = hocon.parse(wrapper, env={})
    got = json.loads(cfg._render_json_for_test())
    assert _norm(got) == _norm(expected), (
        f"properties-syntax/{stem}: mismatch against the Lightbend oracle\n"
        f"  got:      {json.dumps(got, sort_keys=True)}\n"
        f"  expected: {json.dumps(expected, sort_keys=True)}"
    )


def test_group_complete() -> None:
    """Guard: all five canonical ps scenarios must be discovered."""
    discovered = {stem for stem, _, _ in _FIXTURES}
    missing = _KNOWN_STEMS - discovered
    assert not missing, f"properties-syntax group is missing fixtures: {sorted(missing)}"
